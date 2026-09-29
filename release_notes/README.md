# Release notes

One `.md` file per meaningful change, newest at the top of this index. Each file says what
changed, why, and which files were touched — a running record separate from the phase docs
(`restaurant_voice_agent_plan.md`, `docs/`), which describe what the project *is*, not the
history of how it got there.

Naming: `YYYY-MM-DD-short-slug.md`.

**Studying the voice agent?** The maths and model structure behind each Phase 4 step
(sampling, RMS and decibels, resampling and aliasing, Silero's Fourier/convolution/LSTM/sigmoid
stages, endpointing) are explained in
[`docs/phase4_voice_agent_guide.md`](../docs/phase4_voice_agent_guide.md). The notes below
hold the real logs from each run; the guide explains why they look the way they do.

## Index

- [2026-09-28-phase4-step3-endpointing.md](2026-09-28-phase4-step3-endpointing.md)
  — step 3: SPEECH START / END events, blip filtering, hysteresis, utterances saved as .wav.
- [2026-09-28-phase4-step2-resample-and-vad.md](2026-09-28-phase4-step2-resample-and-vad.md)
  — step 2: 48k stereo → 16k mono, Silero VAD, RMS vs VAD logged side by side.
- [2026-09-28-phase4-step1-raw-audio-in.md](2026-09-28-phase4-step1-raw-audio-in.md)
  — hand-built voice agent, step 1: browser mic → WebRTC → Python, frames printed.
- [2026-09-28-phase4-pivot-away-from-livekit.md](2026-09-28-phase4-pivot-away-from-livekit.md)
  — reversed the LiveKit approach below; the voice agent is built by hand instead.
- [2026-09-28-phase4-milestone1-step1-vad-stt.md](2026-09-28-phase4-milestone1-step1-vad-stt.md)
  — (superseded) Phase 4 begins: VAD + Groq STT only, no LLM/TTS yet.
- [2026-09-28-phase3-complete.md](2026-09-28-phase3-complete.md) — Phase 3: the LangGraph
  text agent, tool-call batching, multi-provider LLM switch, LangSmith tracing.
