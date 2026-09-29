# Phase 4 pivot: no framework — built by hand

## What changed

Reversed the previous entry
([2026-09-28-phase4-milestone1-step1-vad-stt.md](2026-09-28-phase4-milestone1-step1-vad-stt.md)).
The voice agent will **not** use LiveKit, Pipecat, or any similar framework. It's assembled
by hand from lower-level libraries instead, following the pattern of a reference WhatsApp
voice agent project shared during planning.

- **Removed**: `backend/voice_agent/worker.py`, the `livekit-agents[...]`/`langchain[openai]`/
  `python-dotenv` lines in `requirements.txt`, the `LIVEKIT_*` placeholders in
  `.env.example`. (Real `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` values already
  in the local `.env` were left alone — unused now, but not deleted, since they weren't
  placeholders this project added.)
- **Added**: `aiortc` (pure-Python WebRTC) and `av` (PyAV, audio frame handling) to
  `requirements.txt`.

## Why

For a learning project, a framework like LiveKit Agents hides exactly the layer this
project wants to see and build: turn-taking, barge-in, endpointing, and how VAD/STT/TTS
frames actually move through the system. Building it by hand means every one of those
pieces is code this project owns and can inspect, not a framework's internal callback.

## New architecture (replaces the LiveKit-based plan)

| Job | Library | Kind |
|---|---|---|
| WebRTC transport (answer the call, send/receive audio) | `aiortc` (`RTCPeerConnection`, `MediaStreamTrack`) | Code (library) |
| Audio frames, resampling | `av` (PyAV) | Code (library) |
| Audio math (loudness, mixing) | `numpy` (already installed) | Equation |
| Voice activity detection | Silero VAD, via `torch.hub` (already used in Phase 1's audio lab) | Model |
| Speech-to-text | Groq Whisper API (already integrated) | Model (hosted) |
| LLM / tools | `backend/agent/graph.py` (Phase 3, unchanged) | Existing code |
| Text-to-speech | ElevenLabs (key already in `.env`) | Model (hosted) |
| Turn-taking, barge-in, endpointing | Hand-written, in this project | Code (ours) |

For now: a signaling connection between a browser test page and the Python backend over
WebRTC directly (no telephony provider yet). WhatsApp calling is still explicitly future
work, same as the original plan always said — this only changes *how* the agent's own
pipeline is built, not when WhatsApp integration happens.

## Status

Planning only at this point — no new pipeline code written yet. Next: verify `aiortc`'s
current API before writing the first runnable piece (raw audio frames flowing from a
browser mic into the Python process, before VAD or anything else is layered on).
