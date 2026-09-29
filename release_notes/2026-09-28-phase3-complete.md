# Phase 3: LangGraph text agent

## What this covers

Everything built for Phase 3 — the text-only conversational agent that sits on top of
Phase 2's tools. Written retroactively as the first entry in this log; entries from here on
are written as each change happens, not after the fact.

## What was built

- **`backend/agent/`**: a 2-node LangGraph (`agent` ↔ `tools`) — `session.py`
  (`SessionRef`, the per-call id holder the LLM never sees directly), `tools_binding.py`
  (14 tools wrapping Phase 2's functions), `prompts.py` (system prompt: menu, business
  facts, today's date, behavioral rules), `llm.py`, `state.py`, `graph.py`, `cli.py`.
- **`backend/tools/orders.py`**: added `cancel_order`, mirroring the existing
  `cancel_reservation`.
- **`backend/tools/clock.py`** (new): `get_today()` in the cafe's timezone, loaded once per
  session onto `SessionRef.today` — not a callable LLM tool, so the model can't invent a
  date.
- **Token-cost work**: `backend/agent/formatting.py` turns tool results into short
  sentences instead of raw JSON before they enter the conversation. `search_menu` and
  `add_item` both take a list, so several items named in one sentence cost one tool call
  instead of one per item.
- **Multi-provider LLM**: `AGENT_LLM_PROVIDER` in `backend/constant.py` switches between
  `groq`, `nvidia`, and `openrouter` — one exhausting its daily quota doesn't block testing.
- **LangSmith tracing**: `LANGSMITH_TRACING=true` in `.env` turns on full call tracing, no
  code change needed elsewhere (LangChain checks for it automatically).
- **Error handling**: a tool's `ValueError` becomes a plain-language message the model can
  react to; anything else crashes loudly instead of being hidden. A model-side failure
  (invalid tool call) is retried once before falling back to "could you say that again?"
- **`evals/run_scenarios.py`**: runs the 30 scenarios from
  `docs/phase3_test_conversations.md` against the real agent and saves transcripts — not a
  pass/fail suite, since LLM phrasing isn't deterministic.
- **`docs/phase3_test_conversations.md`**: the 30 scenarios themselves.
- **60+ new automated tests** across `tests/test_agent_graph.py`, `tests/test_formatting.py`,
  `tests/test_llm_config.py` — all free to run (no LLM calls) except one Groq smoke test.

## Real bugs found and fixed along the way

- A `ValueError` from a tool crashed the whole CLI process instead of becoming a message the
  model could react to — `ToolNode`'s default error handler only catches its own internal
  error type, not ours.
- The model would say "I'll add that" without having called `add_item` yet.
- The model would sometimes end a turn with empty content after a chain of tool calls.
- `llama-3.3-70b-versatile` (Groq) was deprecated/access-gated after this codebase's
  knowledge cutoff — switched to `openai/gpt-oss-120b`, verified against Groq's own current
  model listing rather than guessed.

## Status

Not fully done: the code and tooling are complete, but the 30-scenario checklist hasn't been
run systematically yet (only a handful of scenarios tried by hand). That's the actual
remaining work before Phase 3 can be called finished.
