# Learning notes: how this project is put together

Everything here is written for me to revisit later. For each piece: **what** it is, **where** it lives, **why** it exists.

---

## 1. The big picture

```
 Caller / browser
       |
       v
 [ Voice agent ]  (backend/agent, later)   <-- STT -> LLM -> TTS
       |  calls tools
       v
 [ Backend API ]  (backend/api)  FastAPI   <--- [ React dashboard ] (frontend/)
       |
       v
 [ Postgres ]  data + rules          [ Redis ]  live events
      (both run in Docker)
```

- **Postgres** stores the truth: menu, tables, reservations, orders.
- **Redis** carries live events (what the agent is doing right now) to the dashboard.
- **Backend** is Python. The rules (no double booking, menu match) live in code and in the database, never in the LLM prompt.
- **Frontend** is React. It only displays things and calls the backend.

---

## 2. Folder map

```
voice_agent_cafe/
├── restaurant_voice_agent_plan.md   the build plan
├── learning.md                      this file
├── docs/spec.md                     the cafe: hours, tables, menu, delivery rules
├── docker-compose.yml               starts Postgres + Redis
├── .env / .env.example              settings and secrets (.env is never committed)
├── .python-version                  tells pyenv which Python to use here
├── requirements.txt                 Python libraries
├── setup.py                         makes the project installable as a library
├── alembic.ini                      migration tool config
├── pytest.ini                       test config
├── logger/                          shared logging
├── exception/                       shared custom exception
├── backend/
│   ├── constant.py                  fixed values (hours, limits, fees)
│   ├── config.py                    values from .env (DB, keys)
│   ├── api/main.py                  FastAPI app, /health
│   └── agent/                       voice agent (later)
├── database/
│   ├── connection.py                engine, sessions, health checks
│   ├── models.py                    table definitions in Python
│   └── migrations/                  Alembic: versioned schema changes
├── frontend/                        React (Vite) dashboard
│   ├── package.json, vite.config.js, index.html
│   └── src/ (main.jsx, App.jsx, constants.js)
├── evals/                           test conversations (later)
└── logs/                            created automatically by the logger
```

**Why split like this:** each folder has one job. `backend` never imports from `frontend`. `database` knows nothing about FastAPI. Shared helpers (`logger`, `exception`) sit at the top so every part can use them.

---

## 3. Docker and docker-compose

**What:** Docker runs programs in isolated containers. `docker-compose.yml` describes several containers and starts them together.

**Why:** I don't install Postgres or Redis on my machine. One command gives everyone the same versions, and I can delete everything cleanly.

Key ideas in [docker-compose.yml](docker-compose.yml):
- `image: postgres:16` is the ready-made program to run.
- `ports: "6380:6379"` is **host port : container port**. Redis listens on 6379 *inside* the container. My machine reaches it on 6380. I changed the host side because 6379 was already used on my machine.
- `${POSTGRES_PORT:-5432}` reads a value from `.env`; if it's missing, it uses the default after `:-`.
- `volumes: pgdata` keeps the database files after the container stops. Without it, data would vanish.
- `healthcheck` runs a small command repeatedly. `docker compose ps` shows "healthy" only when it passes (`pg_isready`, `redis-cli ping`).

Commands:
```bash
docker compose up -d          # start in the background
docker compose ps             # status (want: healthy)
docker compose logs postgres  # read a container's output
docker compose down           # stop and remove containers (data stays in the volume)
docker compose down -v        # ALSO delete the data (fresh start)
```

**Lesson learned:** "address already in use" means another program owns that host port. Find it with `sudo lsof -i :PORT`, or pick a different host port.

---

## 4. Postgres (the database)

**What:** A relational database. Data lives in tables with typed columns and rules.

**Why Postgres and not a simple file:** I need the database itself to refuse a double booking, even when two calls happen at the same instant. Postgres has an EXCLUDE constraint for exactly this.

Tables (defined in [database/models.py](database/models.py)):

| Table | Purpose |
|---|---|
| `cafe_tables` | physical tables and seats |
| `reservations` | bookings with status held / confirmed / cancelled / expired |
| `menu_items`, `modifiers`, `menu_item_modifiers` | menu, options like "no onion", and which option fits which item |
| `customers`, `addresses`, `delivery_pincodes` | who orders, where, and the delivery area |
| `orders`, `order_items`, `order_item_modifiers` | the order and its lines |

Ideas worth remembering:
- **Constraint = a rule the database enforces.** CHECK (`quantity > 0`), UNIQUE (no duplicate names), FOREIGN KEY (a row must point at a real row), EXCLUDE (no overlapping time ranges).
- **`no_double_booking`:** `EXCLUDE USING gist (table_id WITH =, tstzrange(starts_at, ends_at) WITH &&) WHERE (status IN ('held','confirmed'))`. It means: two active reservations with the same table and overlapping time can't both exist. Booking 12:00-13:30 then 13:30-15:00 is allowed, because the end time is exclusive.
- **Race condition:** two requests act at once. The database serializes them, so the second one fails with an error. The code must catch that error and answer politely.
- **Hold then confirm:** a hold reserves a slot for 5 minutes. A constraint can't use `now()`, so the tool must mark expired holds `expired`, and `confirm_reservation` must check the hold hasn't expired.
- **Order lines copy name and price** so old orders don't change when the menu changes.
- **Money uses `Numeric(10,2)`, never float.** Floats give errors like 0.1 + 0.2 = 0.30000000000000004.
- **Times are stored in UTC** (`timestamptz`) and shown in `Asia/Kolkata`.
- **Rules the DB can't enforce** (the tools must): one spice level per item, totals recomputed from lines, expired holds cleaned up.

Look inside the database:
```bash
docker exec -it cafe_postgres psql -U cafe -d cafe
\dt              # list tables
\d modifiers     # describe one table
\q               # quit
```

---

## 5. Alembic (migrations)

**What:** Version control for the database schema. Each file in `database/migrations/versions/` is one step (`0001`, `0002`, ...).

**Why:** Changing tables by hand is untraceable. Migrations let me rebuild the exact schema anywhere and roll changes forward or back.

- `alembic upgrade head` applies all steps not yet applied. Alembic remembers progress in the `alembic_version` table.
- `alembic downgrade -1` undoes the last step.
- [database/migrations/env.py](database/migrations/env.py) connects Alembic to my settings and models.
- I wrote `0001` by hand because Alembic's auto-generate can't create the extensions or the EXCLUDE rule.
- **Never edit a migration that has already been applied.** Add a new one (that's why `0002` exists).
- Extensions: `btree_gist` (needed by the EXCLUDE rule), `pg_trgm` (fuzzy text search later).

---

## 6. Redis

**What:** A very fast in-memory store, used here for publish/subscribe messages.

**Why:** When the agent calls a tool, the dashboard should show it live. The agent publishes an event to Redis, and the backend forwards it to the browser. Postgres is for what must last; Redis is for what's happening right now.

Not used yet except the health check.

---

## 7. Backend (Python, FastAPI)

**FastAPI:** a web framework. `@app.get("/health")` turns a function into an HTTP endpoint. It's async, so it can wait on the database without blocking other requests.

**uvicorn:** the server that runs the app: `uvicorn backend.api.main:app --reload`. `backend.api.main` is the module path, `app` is the variable. `--reload` restarts on file changes (development only).

**async / await:** while waiting for the database or a network call, Python can serve other work. Voice needs this, because many things wait at once.

**SQLAlchemy:** lets me write Python classes for tables and queries instead of raw SQL. **asyncpg** is the driver that talks to Postgres. The URL `postgresql+asyncpg://user:pass@host:port/db` selects both.

**Two places for settings, on purpose:**
- [backend/config.py](backend/config.py) reads `.env`. It holds things that change per machine or are secret (passwords, API keys, ports).
- [backend/constant.py](backend/constant.py) holds fixed business values (opening hours, max party size, fees). It's committed to git.

**CORS:** a browser blocks a page from calling a different origin. The React dev server runs on port 5173 and the API on 8000, so the API must explicitly allow 5173 (`CORS_ORIGINS`).

**Health endpoint:** `/health` checks Postgres and Redis and returns `{"ok": true, ...}`. Habit: every service gets one.

---

## 8. Logger and exception (shared)

**Logger** ([logger/__init__.py](logger/__init__.py)): importing it sets up logging once.
```python
from logger import logging
logging.info("order created: %s", order_id)
```
- Writes to the console and to `logs/<timestamp>.log`.
- Rotates files at 5 MB and keeps 3 backups.
- Use levels: `debug` (details), `info` (normal events), `warning` (odd but fine), `error` (something failed).
- Fixed vs the template I started from: the log folder is now inside the project, and handlers aren't duplicated on reload.

**Exception** ([exception/__init__.py](exception/__init__.py)): wraps any error with the file name and line number, and logs it.
```python
import sys
from exception import CafeException

try:
    do_something()
except Exception as e:
    raise CafeException(e, sys) from e
```
`from e` keeps the original error chained, so the full traceback stays visible.

---

## 9. Making the project importable (`setup.py`, `-e .`, `__init__.py`)

- A folder with `__init__.py` is a **package**. That's what makes `from backend.constant import X` work.
- [setup.py](setup.py) with `find_packages()` lists every package. `requirements.txt` starts with `-e .`, which installs the project itself in **editable** mode: I edit code and changes apply immediately, and imports work from any folder.
- `setup.py` reads `requirements.txt` for dependencies and skips the `-e .` line.
- `frontend/` has no `__init__.py`, because it isn't Python.

---

## 10. Environment: Python versions and venv

- **venv** is a private folder of libraries for this project, so versions don't clash with other projects. Create it once, activate it in every new terminal:
  ```bash
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
- **pyenv** manages Python versions. `.python-version` says 3.12.10, so pyenv picks it automatically inside this folder.
- **Why not Python 3.14:** it's too new. Libraries planned later (torch, LiveKit, librosa) may not support it yet. 3.12 is the safe choice.
- **conda `(base)`** in the prompt is a different Python manager. It can shadow pyenv, so check `python --version` before creating the venv.

---

## 11. Frontend (React + Vite)

- **Node.js / npm:** runs JavaScript outside the browser. `npm` installs JavaScript packages, like pip does for Python.
- **React:** builds the UI from components (functions that return HTML-like JSX). `useState` holds data that changes; `useEffect` runs code such as fetching from the API.
- **Vite:** the dev server and bundler. `npm run dev` serves the app on port 5173 with instant reload.
- [frontend/package.json](frontend/package.json) lists the dependencies and scripts. `node_modules/` is what `npm install` creates. It is ignored by git.
- [frontend/src/constants.js](frontend/src/constants.js) keeps values like the API URL in one place.
- The starter page calls `/health` every 2 seconds and shows Postgres and Redis status.
- Later: live calls, call sheet vs DB, latency waterfall, menu manager, metrics.

---

## 12. `.env`, `.gitignore`

- `.env` holds secrets and per-machine values. `.env.example` is the safe template that is committed. If I add a setting, I add it to both.
- `.gitignore` keeps out `.env`, `.venv/`, `node_modules/`, `logs/`, audio files.

---

## 13. Daily commands

```bash
# Start infrastructure
docker compose up -d && docker compose ps

# Database schema
alembic upgrade head

# Backend (terminal 1, venv active)
uvicorn backend.api.main:app --reload

# Frontend (terminal 2)
cd frontend && npm install && npm run dev

# Check
http://localhost:8000/health
http://localhost:5173
```

---

## 14. Problems hit while setting up, and what they taught me

| Problem | Cause | Fix |
|---|---|---|
| `port 6379 already in use` | a local Redis already owned the port | change the host port in compose and `.env` (6380) |
| `password authentication failed for user "cafe"` | the app reached a *different* Postgres on 5432, or the container wasn't running | check `docker compose ps -a`, `sudo lsof -i :5432`, use another host port |
| Postgres container "Created" but never running, `PORTS` column empty | a local Postgres (found with `lsof`) already owned 5432, so Docker couldn't publish the port and the app talked to the wrong database | `POSTGRES_PORT=5433` in `.env`, then `docker compose down` and `up -d` so the container is recreated with the mapping |
| `pyenv: python3.12: command not found` | pyenv only exposes versions it's told to use | `.python-version` file, or `pyenv local 3.12.10`, then `python -m venv` |
| venv was Python 3.14 | wrong interpreter picked | delete `.venv`, recreate with 3.12 |

General lesson: read the error's last line first. It usually names the real cause.

---

## 15. Phase 2 tools: what exists and two real bugs it caught

`backend/tools/` now has `menu_cache.py`, `search_menu.py`, `reservations.py`, `orders.py`,
`business_info.py` - every tool the plan lists for Phase 2. I wrote them, then ran a scripted
check against the live dev DB (28 checks: search matching, the double-booking race, hold
expiry, modifier group conflicts, minimum order, sold-out re-check at confirm, idempotent
confirm). Two real bugs turned up, worth remembering because they're the kind that only
show up when you actually run the code, not when reading it:

- **`hold_slot` crashed with `MissingGreenlet`** after losing a race for one table and
  trying the next candidate. Cause: `session.rollback()` expires every ORM object tied to
  that session, and touching an expired object's attribute (`table.id`) afterwards tries to
  silently reload it from the DB - async SQLAlchemy can't do that implicitly, only via an
  explicit `await`. Fix: read `table.id`/`table.name` into plain values *before* the loop
  that might roll back, and never touch the ORM object again after a rollback.
- **`search_menu` scored a gibberish query as a "near match"** against "glass noodles" -
  `rapidfuzz`'s `WRatio` blends several ratio strategies and can score unrelated short
  strings surprisingly high. Fixed by raising `MIN_THRESHOLD` from 45 to 55; still just a
  hand-picked number, not something measured against real conversations yet (that's Phase 3).

General lesson: an `AsyncSession` object becomes unsafe to touch after `rollback()` or
`commit()` unless you re-fetch or already captured what you needed as plain data first.

## 16. Glossary

- **Container:** an isolated running program. **Image:** its template.
- **Migration:** a versioned schema change.
- **Idempotent:** doing it twice has the same effect as once (needed for `confirm_order`).
- **Race condition:** two actions at once give a wrong result.
- **Async:** waiting without blocking other work.
- **Editable install (`-e .`):** the installed library points at my source files.
