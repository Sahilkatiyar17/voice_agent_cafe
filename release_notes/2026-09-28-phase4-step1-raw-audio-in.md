# Phase 4, step 1: raw audio from the browser into Python

## What changed

The first piece of the hand-built voice agent. A browser page sends its microphone to a
Python process over WebRTC; the process prints what the audio frames look like. No VAD,
STT, LLM or TTS yet.

- **`backend/voice_agent/server.py`** (new): a small FastAPI app on port 8081.
  - `POST /offer` does the one-time WebRTC handshake. It takes the browser's SDP offer,
    creates an `aiortc` `RTCPeerConnection`, and returns the answer.
  - `consume_audio()` reads every incoming `av.AudioFrame`. It logs the first frame's format
    in full, then an RMS loudness number about once a second.
- **`backend/voice_agent/static/index.html`** (new): the test page. It uses the browser's
  built-in `RTCPeerConnection` (no SDK), with `echoCancellation: true`, which is the AEC
  from the plan, handled by the browser.

## Concepts visible in this step

- **Signaling:** the SDP offer/answer is just text describing the media and how to reach
  each side. After this one HTTP exchange, audio flows directly over WebRTC.
- **What the browser actually sends:** the first logged frame shows the real sample rate
  and layout. It's expected to be 48 kHz (WebRTC's Opus codec). Silero VAD and Whisper want
  16 kHz mono, which is why step 2 has to resample.
- **RMS loudness** `sqrt(mean(x²))`: the first *equation* in the pipeline. It's a rough
  "is there sound?" signal. Step 2 replaces it with Silero VAD, a *model*, to show the
  difference between loudness and actual speech detection.

## Design choices

- **HTTP `POST /offer`, not a WebSocket:** this is aiortc's own example pattern. It works
  because both sides gather all their network candidates before exchanging descriptions,
  so one request/response is enough.
- **Separate server, not added to `backend/api/main.py`:** kept apart until Phase 5 merges
  the dashboard, API and voice pieces.

## How to run

```bash
pip install -r requirements.txt   # picks up aiortc and av
uvicorn backend.voice_agent.server:app --host 0.0.0.0 --port 8081
```

Open http://localhost:8081, click Start, allow the microphone, and speak.

## Known risk

The browser runs on Windows and the server runs inside WSL2. If the page shows the
connection stuck at `checking` or `failed`, WebRTC's UDP traffic probably isn't crossing
between Windows and WSL. That's a networking issue, not a code issue.

Result from the first run: this risk didn't happen (see below).

## What we observed on the first run (2026-09-28)

### The full log

(The ICE candidate lines before this point were cut off when the log was copied.)

```
[ 2026-09-28 15:35:27,262 ] root - INFO - Connection state: connecting
[ 2026-09-28 15:35:27,262 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('10.255.255.254', 49618) -> ('172.17.208.1', 50275)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,281 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.17.211.55', 43518) -> ('172.17.208.1', 50275)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,302 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.23.0.1', 35356) -> ('172.17.208.1', 50275)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,323 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.20.0.1', 41775) -> ('172.17.208.1', 50275)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,342 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.18.0.1', 39583) -> ('172.17.208.1', 50275)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,362 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.19.0.1', 55849) -> ('172.17.208.1', 50275)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,382 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.22.0.1', 59358) -> ('172.17.208.1', 50275)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,402 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.21.0.1', 42344) -> ('172.17.208.1', 50275)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,422 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('10.255.255.254', 49618) -> ('192.168.1.39', 50276)) State.WAITING -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,443 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.17.211.55', 43518) -> ('192.168.1.39', 50276)) State.FROZEN -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,464 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.23.0.1', 35356) -> ('192.168.1.39', 50276)) State.FROZEN -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,485 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.20.0.1', 41775) -> ('192.168.1.39', 50276)) State.FROZEN -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,506 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.18.0.1', 39583) -> ('192.168.1.39', 50276)) State.FROZEN -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,526 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.19.0.1', 55849) -> ('192.168.1.39', 50276)) State.FROZEN -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,546 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.22.0.1', 59358) -> ('192.168.1.39', 50276)) State.FROZEN -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,567 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.21.0.1', 42344) -> ('192.168.1.39', 50276)) State.FROZEN -> State.IN_PROGRESS
[ 2026-09-28 15:35:27,785 ] aioice.ice - INFO - Connection(1) Check CandidatePair(('172.17.211.55', 43518) -> ('172.17.208.1', 50275)) State.IN_PROGRESS -> State.SUCCEEDED
[ 2026-09-28 15:35:27,787 ] aioice.ice - INFO - Connection(1) ICE completed
[ 2026-09-28 15:35:27,798 ] root - INFO - Connection state: connected
[ 2026-09-28 15:35:27,898 ] root - INFO - First frame: format=s16 layout=stereo sample_rate=48000 samples_per_channel=960 array_shape=(1, 1920) dtype=int16  (20.0 ms of audio per frame)
[ 2026-09-28 15:35:28,884 ] root - INFO - frame 50  rms=442
[ 2026-09-28 15:35:29,878 ] root - INFO - frame 100  rms=108
[ 2026-09-28 15:35:30,879 ] root - INFO - frame 150  rms=196
[ 2026-09-28 15:35:31,878 ] root - INFO - frame 200  rms=311
[ 2026-09-28 15:35:32,880 ] root - INFO - frame 250  rms=415
[ 2026-09-28 15:35:33,877 ] root - INFO - frame 300  rms=24
[ 2026-09-28 15:35:34,882 ] root - INFO - frame 350  rms=32
[ 2026-09-28 15:35:35,881 ] root - INFO - frame 400  rms=70
[ 2026-09-28 15:35:36,879 ] root - INFO - frame 450  rms=3583
[ 2026-09-28 15:35:37,880 ] root - INFO - frame 500  rms=186
[ 2026-09-28 15:35:38,880 ] root - INFO - frame 550  rms=1372
[ 2026-09-28 15:35:39,878 ] root - INFO - frame 600  rms=17
[ 2026-09-28 15:35:40,879 ] root - INFO - frame 650  rms=49
[ 2026-09-28 15:35:41,878 ] root - INFO - frame 700  rms=141
[ 2026-09-28 15:35:42,878 ] root - INFO - frame 750  rms=3748
[ 2026-09-28 15:35:43,878 ] root - INFO - frame 800  rms=3290
[ 2026-09-28 15:35:44,878 ] root - INFO - frame 850  rms=1027
[ 2026-09-28 15:35:45,878 ] root - INFO - frame 900  rms=1058
[ 2026-09-28 15:35:46,879 ] root - INFO - frame 950  rms=212
[ 2026-09-28 15:35:47,878 ] root - INFO - frame 1000  rms=746
[ 2026-09-28 15:35:48,886 ] root - INFO - frame 1050  rms=692
[ 2026-09-28 15:35:49,879 ] root - INFO - frame 1100  rms=44
[ 2026-09-28 15:35:50,879 ] root - INFO - frame 1150  rms=42
[ 2026-09-28 15:35:51,131 ] root - INFO - Audio track ended after 1162 frames
[ 2026-09-28 15:35:51,138 ] root - INFO - Connection state: closed
```

The explanation below works through this log section by section.

### 1. ICE: finding a network path

WebRTC first has to find a route between the browser and Python. Each side lists every
address it could be reached on (its "candidates"), then `aioice` sends test packets for every
pairing:

- **Python's addresses (inside WSL):**
  - `172.17.211.55` is WSL's own IP.
  - `172.18.0.1` to `172.23.0.1` are Docker's internal networks (Postgres and Redis).
  - `10.255.255.254` is another WSL virtual interface.
- **Browser's addresses (on Windows):**
  - `172.17.208.1` is Windows' side of the link into WSL.
  - `192.168.1.39` is the laptop's LAN/Wi-Fi address.

Each pair moves through `FROZEN → WAITING → IN_PROGRESS`, and the first one to answer wins:

```
('172.17.211.55', 43518) -> ('172.17.208.1', 50275)  SUCCEEDED
ICE completed
Connection state: connected
```

This search is why WebRTC and phone calls take a moment to connect.

### 2. The first frame: what the browser actually sends

```
format=s16 layout=stereo sample_rate=48000 samples_per_channel=960 array_shape=(1, 1920)
```

| Field | Meaning |
|---|---|
| `s16` | 16-bit signed integer samples, from -32768 to 32767 |
| `48000` | 48,000 samples per second, the Opus codec's rate (not the mic's native rate) |
| `960` samples | 960 ÷ 48000 = 20 ms per frame, so 50 frames arrive every second |
| `stereo`, shape `(1, 1920)` | Two channels interleaved in one row (L, R, L, R…): 960 × 2 = 1920. A laptop mic is mono, so both channels are almost certainly copies |

Silero VAD and Whisper both want 16 kHz mono, so step 2 has to convert 48k stereo → 16k mono.

### 3. RMS: loudness, the first equation

`rms = sqrt(mean(x²))` is the average size of the samples.

- **Quiet:** 17–70 (room noise).
- **Speaking:** 442, 1372, 3583, 3748.
- **In between:** 108–212.

These numbers are noisier than they look, because RMS was computed on **one 20 ms frame out
of every 50**, not averaged over the second. `frame 300 rms=24` doesn't mean a silent second;
that 20 ms slice fell into a gap between words. This shows why loudness is a weak speech
detector:

- **Pauses** mid-sentence look like silence.
- **A cough or door slam** looks like speech.
- **No threshold** separates the two reliably.

### 4. The end

`Audio track ended after 1162 frames` works out to 1162 × 20 ms ≈ 23 s, from Start to Stop.
Here's the shutdown sequence:

1. The browser stopped the track.
2. aiortc raised `MediaStreamError`.
3. The read loop exited cleanly.
4. The connection closed.
