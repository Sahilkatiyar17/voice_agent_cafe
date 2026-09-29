# Phase 4, Milestone 1 step 1: VAD + Groq STT only

## What changed

The first runnable piece of the voice agent — deliberately small. No LLM, no TTS. Just
Silero VAD + Groq Whisper STT, printing every partial and final transcript to the console,
so the pipeline can be confirmed working before anything else is layered on.

- **`backend/voice_agent/worker.py`** (new): a LiveKit Agents worker. Listens for the
  `user_input_transcribed` event and prints `[FINAL]`/`[partial]` transcripts.
- **`requirements.txt`**: added `livekit-agents[silero,groq,elevenlabs,langchain]~=1.8`,
  `langchain[openai]`, `python-dotenv`.
- **`.env` / `.env.example`**: added `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
  (need a free project at cloud.livekit.io).

## Why this shape

LiveKit's plugin packaging turned out to have changed since this codebase's knowledge
cutoff (extras syntax like `livekit-agents[groq]`, not separate `livekit-plugins-*`
packages) — confirmed against docs.livekit.io directly before writing anything, the same
discipline applied to the Groq model-deprecation issue in Phase 3. The worker's top-level
structure (`AgentServer` + `@server.rtc_session`) is also newer than the classic
`WorkerOptions(entrypoint_fnc=...)` pattern and was verified the same way, across several
LiveKit doc pages, since a single page gave inconsistent/abbreviated examples.

**One thing this confirms, not just assumes:** LiveKit has an official LangChain/LangGraph
plugin (`livekit.plugins.langchain.LLMAdapter`) that takes a compiled LangGraph graph
directly. This means Phase 3's `backend/agent/graph.py` plugs into the voice agent without
a rewrite — validating the decision (made against my recommendation at the time) to build
Phase 3 on LangGraph instead of a plain state machine.

## What's not yet verified

`session.start()` was called with a minimal `Agent(instructions="")` since every fetched
LiveKit example passes a non-None `agent`, but I could not confirm from the docs whether
that's strictly required with no LLM. If this line errors on first run, that's the specific
thing to report back.

## How to run it

```bash
pip install -r requirements.txt
python -m backend.voice_agent.worker dev
```

Connect via LiveKit's hosted Agents Playground (agents-playground.livekit.io) — no custom
frontend yet, that's Milestone 2.

## Not done yet

This is step 1 of Milestone 1 only. TTS (ElevenLabs) and the LangGraph agent are not wired
in yet — next steps, one at a time, once this one is confirmed working.
