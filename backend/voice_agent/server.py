"""
Voice agent server.

Step 1 (done): a browser page opens a WebRTC connection to this process and sends its
microphone; we read the decoded audio frames.
Step 2 (done): each frame is converted to 16 kHz mono (audio.py) and scored by Silero VAD
(vad.py).
Step 3 (this version): the VAD probabilities drive an endpointer (endpointing.py) that
emits SPEECH START / SPEECH END events, ignores short blips, and saves each finished
utterance as a .wav file - exactly the audio step 4 will send to speech-to-text.
No STT, LLM or TTS yet.

How the connection is set up (signaling):
  1. The browser creates an RTCPeerConnection, adds its mic track, and makes an SDP
     "offer" - a text description of what media it wants to send and how to reach it.
  2. It POSTs that offer to /offer.
  3. We create our own RTCPeerConnection (aiortc), apply the offer, create an "answer",
     and send it back. After that, audio flows directly over WebRTC - HTTP is only used
     for this one-time handshake.

Run (from the project root, venv active):
    uvicorn backend.voice_agent.server:app --host 0.0.0.0 --port 8081
Then open http://localhost:8081 in the browser, click Start, and speak.

Endpointing settings can be changed per run without editing code - see endpointing.py:
    MIN_SILENCE_MS=300 uvicorn backend.voice_agent.server:app --host 0.0.0.0 --port 8081
Set LOG_VAD_EVERY_SECOND=1 to also get step 2's per-second RMS/VAD line.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.voice_agent.audio import TARGET_SAMPLE_RATE, MonoResampler
from backend.voice_agent.endpointing import MIN_SPEECH_MS, Blip, Endpointer, SpeechEnd, SpeechStart
from backend.voice_agent.vad import SileroVAD
from logger import logging

STATIC_DIR = Path(__file__).parent / "static"
# Saved utterances, one sub-folder per call. *.wav and recordings/ are both gitignored.
RECORDINGS_DIR = Path(__file__).parent / "recordings"

LOG_VAD_EVERY_SECOND = os.environ.get("LOG_VAD_EVERY_SECOND") == "1"
REPORT_EVERY_N_FRAMES = 50  # at 20ms per frame, that's about once a second
SPEECH_THRESHOLD = 0.5  # only used by the optional per-second line

peer_connections: set[RTCPeerConnection] = set()
vad: SileroVAD | None = None  # loaded once at startup - loading takes about a second


@asynccontextmanager
async def lifespan(app: FastAPI):
    global vad
    vad = SileroVAD()
    logging.info("Endpointing settings: %s", Endpointer.describe_settings())
    yield
    # Close any calls still open when the server stops.
    await asyncio.gather(*(pc.close() for pc in peer_connections))
    peer_connections.clear()


app = FastAPI(title="Cafe voice agent", lifespan=lifespan)


class Offer(BaseModel):
    sdp: str
    type: str


def save_utterance(call_dir: Path, number: int, event: SpeechEnd) -> Path:
    call_dir.mkdir(parents=True, exist_ok=True)
    path = call_dir / f"utterance_{number:04d}.wav"
    sf.write(path, event.audio, TARGET_SAMPLE_RATE)
    return path


def log_event(event, call_dir: Path, utterance_count: int) -> int:
    """Logs one endpointing event; saves the audio for a SpeechEnd. Returns the updated
    utterance count."""
    if isinstance(event, SpeechStart):
        logging.info("%7.2fs  SPEECH START", event.at)
    elif isinstance(event, Blip):
        logging.info(
            "%7.2fs  ignored blip: %d ms (below the %d ms minimum)",
            event.at, event.duration_ms, MIN_SPEECH_MS,
        )
    elif isinstance(event, SpeechEnd):
        utterance_count += 1
        path = save_utterance(call_dir, utterance_count, event)
        logging.info(
            "%7.2fs  SPEECH END    %.2fs of speech (turn ended after %d ms of silence) -> %s",
            event.ended_at, event.ended_at - event.started_at, event.silence_ms,
            path.relative_to(RECORDINGS_DIR.parent),
        )
    return utterance_count


async def consume_audio(track: MediaStreamTrack) -> None:
    """Reads every frame the browser sends (an av.AudioFrame: 20 ms, 48 kHz stereo),
    converts it to 16 kHz mono, runs VAD on it, and feeds the VAD results to the
    endpointer."""
    # One call at a time for now: there's a single Silero instance, and it's stateful.
    # Two simultaneous calls would mix each other's state - fine for testing, not beyond.
    vad.reset()
    resample = MonoResampler()
    endpointer = Endpointer()
    call_dir = RECORDINGS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    utterance_count = 0

    frame_count = 0
    sum_squares, sample_count, probabilities = 0.0, 0, []  # optional per-second line only

    while True:
        try:
            frame = await track.recv()
        except MediaStreamError:
            # Caller hung up / clicked Stop - don't lose a sentence they were mid-way through.
            final = endpointer.flush()
            if final is not None:
                utterance_count = log_event(final, call_dir, utterance_count)
            logging.info("Audio track ended after %d frames, %d utterance(s)", frame_count, utterance_count)
            return

        frame_count += 1
        mono = resample(frame)

        if frame_count == 1:
            logging.info(
                "Resampled: %d Hz %s, %d samples/frame  ->  %d Hz mono, %d samples/frame",
                frame.sample_rate, frame.layout.name, frame.samples, TARGET_SAMPLE_RATE, len(mono),
            )

        for probability, window in vad.process(mono):
            probabilities.append(probability)
            for event in endpointer.process(probability, window):
                utterance_count = log_event(event, call_dir, utterance_count)

        if LOG_VAD_EVERY_SECOND:
            sum_squares += float(np.sum(mono.astype(np.float64) ** 2))
            sample_count += len(mono)
            if frame_count % REPORT_EVERY_N_FRAMES == 0 and probabilities:
                rms = (sum_squares / sample_count) ** 0.5 if sample_count else 0.0
                vad_max = max(probabilities)
                speech_windows = sum(p >= SPEECH_THRESHOLD for p in probabilities)
                logging.info(
                    "%5.1fs  rms=%5.0f  vad_max=%.2f |%-10s|  speech windows %2d/%d",
                    frame_count / 50, rms, vad_max, "#" * round(10 * vad_max),
                    speech_windows, len(probabilities),
                )
                sum_squares, sample_count = 0.0, 0
        if frame_count % REPORT_EVERY_N_FRAMES == 0:
            probabilities = []


@app.post("/offer")
async def offer(body: Offer) -> dict:
    pc = RTCPeerConnection()
    peer_connections.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:
        logging.info("Connection state: %s", pc.connectionState)
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            peer_connections.discard(pc)

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        logging.info("Track received: %s", track.kind)
        if track.kind == "audio":
            asyncio.ensure_future(consume_audio(track))

    await pc.setRemoteDescription(RTCSessionDescription(sdp=body.sdp, type=body.type))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
