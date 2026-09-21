# Restaurant Voice Agent: Build Plan

## The idea in one paragraph

A caller phones a restaurant. The agent picks up and helps with two things: **booking a table** or **ordering food for delivery**. It checks the menu, handles special requests ("no onions"), and saves everything in a database. An admin dashboard shows the live call, the agent's tool calls, the timings, and the database changes. English comes first, Hinglish later.

The main goal is **learning by building**. Every phase has concepts to try in practice, and every big idea gets measured with an experiment.

---

## Big decisions (so you don't have to re-think them)

| Question | Decision |
|---|---|
| Menu: RAG or SQL? | **SQL** is the truth. The menu is small, so load it into memory and also put it in the prompt. Use RAG only for fuzzy FAQs like allergens. |
| Is the item on the menu? | A `search_menu` tool answers: **exact match**, **near match** (with suggestions), or **not found**. The LLM never decides this itself. |
| Is it available now? | A separate `is_available` flag, checked again when the order is confirmed. |
| Reservations | The DB must block double booking. Use a hold, then a confirm. |
| Your MD file idea | Keep the live order in a "call sheet" (memory or `.md`) and sync it to the DB in the background. We will **test it against the normal way**, not assume it wins. |
| Voice framework | **LiveKit Agents**. It has VAD, turn detection, phone (SIP) support, and metrics built in. |
| Agent logic (flow control) | Start with **plain LiveKit Agents + your own small state machine**. Try **LangGraph later as an experiment** and compare. |
| Models | APIs for STT, LLM, TTS, behind simple wrapper classes so you can swap them. |
| Where rules live | Database checks (no double booking, menu match, availability) live in **your tools**, never inside the prompt or a graph. |

---

## Libraries and tools

| Job | Tool |
|---|---|
| Language and setup | Python 3.11+, `uv`, `pytest`, `pytest-asyncio`, `ruff`, Docker Compose |
| Voice pipeline | `livekit-agents` with plugins for VAD (Silero), turn detector, STT, LLM, TTS |
| Backend | FastAPI, SQLAlchemy (async), Alembic, Pydantic |
| Database | Postgres (needed for the no-double-booking rule) |
| Fuzzy menu matching | `rapidfuzz` or Postgres `pg_trgm` |
| Live events | Redis pub/sub, then SSE or WebSocket to the browser |
| Dashboard | Next.js, TypeScript, Tailwind, shadcn/ui, Recharts |
| Logging | `structlog` plus your own `events` table |
| Audio experiments | `librosa` or `torchaudio`, `soundfile` |
| Phone | A SIP number from a provider, connected to LiveKit SIP. Check Exotel or Plivo for Indian numbers, or use a foreign number while developing. |
| Tunnels for testing | ngrok or cloudflared |
| **Only for Experiment 3 (Phase 7)** | `langgraph`, `langchain`, and the LiveKit LangChain/LangGraph plugin (check the current LiveKit docs for the exact plugin name) |

Pick specific STT, LLM, and TTS providers by testing 2-3 of each yourself. They change fast.

---

## Phase 0: Setup (2-3 days)

- Create the folders: `agent/`, `api/`, `web/`, `evals/`, `infra/`, `docs/`.
- Run Postgres and Redis with Docker Compose.
- Write a one-page spec: opening hours, tables, a sample menu of about 30 items with modifiers, delivery area, cash on delivery only, and what is out of scope.
- Write down your **latency target** (end of speech to first audio: about 1 second).
- Save times in UTC and read them in `Asia/Kolkata`.

**Done when:** `docker compose up` gives you a working DB and a health check.

---

## Phase 1: Audio basics lab (2-3 days)

This uses what you learned in class. You will *see* the ideas before using the APIs.

- Record yourself. Load it, check the sample rate, and resample 16 kHz to **8 kHz** (phone quality).
- Draw a spectrogram and a mel-spectrogram. Compare them.
- Run **Silero VAD** on a file. Change the threshold and watch what changes.
- Send the 16 kHz and 8 kHz clips to an STT API and compare accuracy.

**Concepts:** sampling, spectrograms, mel scale, VAD, why phone audio hurts STT.

---

## Phase 2: Database and tools, no voice (1 week)

- Tables:
  - `cafe_tables`
  - `reservations`
  - `menu_items` (with `aliases`, `is_available`, `branch_id`)
  - `item_modifiers`
  - `customers`
  - `addresses`
  - `orders`, `order_items`, and their modifiers
- Rule in the DB: no two held or confirmed reservations can overlap on the same table.
- Save the item name and price on each order line, so old orders don't change when prices change.
- Add `branch_id` and `call_id` where needed, so later analysis is easy.
- Tools take **only structured input** (ISO dates, 24-hour times, item IDs, quantities):
  - Reservations: `check_availability`, `hold_slot`, `confirm_reservation`, `cancel_reservation`, `lookup_reservation`
  - Orders: `search_menu`, `update_order`, `set_delivery_address`, `get_order_summary`, `confirm_order`
  - Info: `get_business_info`
- `search_menu` steps: clean the text, check aliases, fuzzy match, then return exact, near, or not found.
- Menu loads into memory at startup and refreshes when the admin edits it.
- `confirm_order` checks availability again inside the DB transaction and is safe to call twice (idempotent).

**Concepts:** transactions, race conditions, hold and expiry, idempotency, fuzzy matching.

**Done when:** 20 parallel bookings for one slot give exactly one winner, "matar paneer" correctly returns "not found, nearest: palak paneer," and totals with modifiers are correct.

---

## Phase 3: Text agent (1 week)

- Write the system prompt with the menu inside. Keep replies short, with no markdown.
- Add intent handling: reservation, order, info, or both in one call.
- Create a **SessionState** object that holds the current order or booking, plus a **current stage** field (for example: `greeting`, `collecting_reservation`, `collecting_order`, `address`, `readback`, `confirmed`). This is your own small state machine.
- Show the state to the LLM as a small call sheet each turn. Build the simple version first (every change is a tool call to the DB), because it is your baseline for Phase 7.
- Keep the state logic behind a small interface, so you can swap it in Phase 7 without rewriting the agent.
- Rules: ask for one missing detail at a time, always read back before confirming, and never write without a spoken yes.
- Start writing **events** now (`tool_call_started`, `llm_response`, and so on). The dashboard will use them later.
- Write 30 scripted test conversations, including "item not on menu," "sold out," "list continental items," and "actually remove the burger."

**Concepts:** function calling, slot filling, state machines, prompt design for voice, context control.

**Done when:** all test conversations pass in text.

---

## Phase 4: Real-time voice in the browser (1-1.5 weeks)

Build the LiveKit agent: **VAD → streaming STT → turn detection → LLM → TTS**, and a small web page to talk to it.

Learn and try each of these:

- **AEC and residual echo suppression:** the browser does this for you here. Test with speakers instead of headphones to hear what happens without it.
- **VAD:** tune the speech and silence settings.
- **Streaming STT:** partial vs final text.
- **Endpointing:** start with a silence timer, then switch to **semantic turn detection**. Notice the tradeoff between cutting people off and waiting too long.
- **Barge-in:** if speech lasts about 150 ms, stop playback and cancel the LLM and TTS streams. Add a **backchannel list** ("yeah", "mm-hmm") so small acknowledgements don't interrupt the agent.
- **Token streaming to TTS:** send text to TTS at the first sentence or comma.
- **Tool calls during interruption:**
  - Read-only tools (like `check_availability`): cancel them.
  - Write tools: nothing is written before the caller says yes. Once a write has started, let it finish in the background and tell the LLM the result, so you never get half-saved orders or double saves.
- **Smarter waiting:** be more patient while the caller says an address or phone number.
- **Agent handoff (optional):** LiveKit lets one agent hand the call to another (for example, a reservation agent and an order agent). Try it if a single agent's prompt gets too long. Check the current docs for the API.

Keep STT, LLM, and TTS behind thin wrapper classes, and keep language-specific things (prompt, filler phrases, backchannel words, thresholds) in one `language_config` file.

**Done when:** you finish one booking and one delivery order in English by voice, and you can interrupt the agent cleanly.

---

## Phase 5: Admin dashboard (1-1.5 weeks)

FastAPI serves the data. Redis sends live events to the browser. Pages:

1. **Live calls:** agent state (listening, thinking, speaking, in tool) and live transcript.
2. **Call sheet vs database:** the draft on one side and the DB rows on the other, with differences highlighted.
3. **Call detail:** transcript, tool calls with inputs and results, and a **latency waterfall** per turn (endpointing, STT, LLM first token, tool time, TTS first byte).
4. **Orders and reservations:** orders by status, and a day view for tables.
5. **Menu manager:** turn items on or off (great for demos).
6. **Metrics:** p50 and p95 time to first audio, tool success rate, interruption rate, cost per call.

For "what the agent is thinking," show tool calls, their inputs and results, and the call sheet. Don't try to show hidden model reasoning.

**Done when:** you can talk to the agent and watch the whole call and every DB change appear live.

---

## Phase 6: Real phone calls (3-5 days)

- Get a SIP number and connect it to LiveKit SIP (inbound trunk and dispatch rule). Then call it from your own phone.
- Handle phone problems: 8 kHz audio (choose a phone-friendly STT), caller ID (fill in the phone number automatically), hangup, silence timeout, and transfer to a human.
- **WhatsApp calling** needs a verified business account and Meta approval, and may not be available in every region. Treat it as an extra goal after normal phone calls work.

**Done when:** you call from your phone, the agent takes an order, and the dashboard shows the call as `pstn`.

---

## Phase 7: Latency lab and experiments (ongoing)

**Rule: measure first, then fix the biggest delay.**

Rough target from end of speech to first audio:

| Stage | Target |
|---|---|
| Endpointing wait | 200-500 ms |
| STT final | 100-300 ms |
| LLM first token | 300-600 ms |
| Database tool | under 50 ms |
| TTS first byte | 100-300 ms |

### Experiment 1: your call sheet idea

The DB write is fast. The slow part of a tool call is the extra LLM round trip. So test three versions on the same scenarios:

- **A:** every change and every readback is a DB tool call (your baseline).
- **B:** in-memory call sheet, DB saved in the background, readback from the sheet.
- **C:** same as B, but the call sheet is a `.md` file.

Compare LLM round trips per turn, p50 and p95 time to first audio, and how often the sheet and DB disagree. Also test what happens if the DB goes down mid-call.

### Experiment 2: menu

Compare menu-in-prompt against a `search_menu` call for every question. Measure latency and wrong-item rate.

### Experiment 3: LangGraph vs your own state machine

Build a second version of the same flow using **LangGraph** as the "LLM" inside LiveKit. The graph decides what to say and which tool to call. VAD, STT, turn detection, and TTS stay in LiveKit. Your tools and DB rules stay the same.

Run both versions on the same test conversations and compare:

- LLM round trips per turn
- p50 and p95 time to first audio
- how cleanly interruptions are handled (especially cancelling a graph run in the middle of a node or a write tool)
- how many lines of code, and how hard it is to debug
- whether checkpoints (saved state) give anything you actually need

Why this is an experiment and not the starting point: extra layers add delay, interruptions are harder to handle inside a graph, your flow is short, and fewer layers are easier to measure and understand.

### Other things to try, roughly in order of payoff

Stream everything, prompt caching, a smaller and faster model for easy turns, keep the agent, DB, and APIs in the same region, keep provider connections open, start the LLM on partial transcripts, cache TTS for fixed phrases, and play a filler phrase only when a tool is actually slow.

Keep a simple log: **change, before p50/p95, after p50/p95**.

---

## Phase 8: Making it production-ready (1 week)

- Timeouts and retries on every API. A backup STT and TTS provider.
- Login for the dashboard. Careful handling of phone numbers. A recording notice at the start of the call.
- Cost per call (STT minutes, LLM tokens, TTS characters, phone minutes).
- Dockerize, add CI tests, and add health checks and alerts.
- Load test with several simulated calls at once.

---

## Phase 9: Hinglish (1-2 weeks)

- **Test STT first.** Record 10-15 clips (dish names, phone numbers, addresses, times) and compare 2-3 providers on normal and 8 kHz audio.
- Add a Hinglish `language_config` and a normalizer between STT and the LLM, for things like "sawa chaar", "nau aath saat", and "parso".
- Add dish aliases and modifier words ("pyaaz mat daalna", "kam teekha").
- Make the LLM write romanized Hinglish with digits, and pick a TTS that says the mix well.
- Retune endpointing for pauses like "matlab..." and update the backchannel list ("haan", "achha" vs "ruko").

**Done when:** the same test conversations pass in English and Hinglish, and you have measured the difference.

---

## Phase 10: Evals and showcase (ongoing)

- Build a simple LLM "fake caller" that runs your scenarios in text mode, plus a few full-voice runs.
- Track: order accuracy (items, quantities, modifiers), reservation correctness, double bookings (target zero), call sheet vs DB mismatches, and latency percentiles.
- Final README with an architecture diagram, latency charts, a screen recording of a call next to the dashboard, and a write-up of your experiment results (A/B/C call sheet, menu, and LangGraph).

---

## About the voice cloning and speaker embedding topics

Since you use APIs for STT and TTS, you won't build mel generators, vocoders, or ECAPA models yourself. They are still useful in Phases 1 and 4, because you will understand *why* phone audio hurts STT and why TTS sounds the way it does. If you want an optional extra at the end, try a custom cloned voice through a TTS API for your restaurant's brand voice.

---

## Order if time is short

Phases 0, 2, 3, 4, then 6 (a working phone call is very motivating), then 5, 7, 8, 9, 10. Phase 1 can be done in an evening.
