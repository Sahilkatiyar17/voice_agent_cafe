# Getting started

Commands to run the project. All paths are from the project root: `/mnt/d/voice_agent_cafe`.

## First time only (one-time setup)

Requirements: Docker, Python 3.12 (via pyenv), Node.js 20+.

```bash
cd /mnt/d/voice_agent_cafe

# 1. Python environment (.python-version makes pyenv pick 3.12.10)
python --version                      # should print 3.12.10
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Settings
cp .env.example .env                  # then check the ports below

# 3. Frontend packages
cd frontend && npm install && cd ..
```

Check `.env`. If your machine already has Postgres or Redis running locally, use different host ports:
```
POSTGRES_PORT=5433
REDIS_PORT=6380
REDIS_URL=redis://localhost:6380/0
```

## Every time you work (3 terminals)

**Terminal 1: database and Redis**
```bash
cd /mnt/d/voice_agent_cafe
docker compose up -d
docker compose ps                     # both should say "healthy"
alembic upgrade head                  # needs the venv; safe to repeat, applies only new migrations
```

**Terminal 2: backend (venv needed)**
```bash
cd /mnt/d/voice_agent_cafe
source .venv/bin/activate
uvicorn backend.api.main:app --reload --host 0.0.0.0
```

**Terminal 3: frontend (no venv needed)**
```bash
cd /mnt/d/voice_agent_cafe/frontend
npm run dev
```

## Check it works

| What | URL | Expect |
|---|---|---|
| API health | http://localhost:8000/health | `{"ok":true,"postgres":true,"redis":true}` |
| API docs | http://localhost:8000/docs | interactive endpoint list |
| Dashboard | http://localhost:5173 | Backend OK, Postgres, Redis all `true` |
| Logs | `logs/` folder | a new `.log` file per start |

## Stop everything

```bash
# Ctrl+C in the backend and frontend terminals, then:
docker compose down                   # keeps the data
docker compose down -v                # also deletes the data (fresh start)
```

## Look inside the database

```bash
docker exec -it cafe_postgres psql -U cafe -d cafe
\dt          # list tables
\q           # quit
```

## Quick fixes

| Problem | Fix |
|---|---|
| `port is already allocated` / `address already in use` | another program owns that port. `sudo lsof -i :5432`, then change the host port in `.env` and run `docker compose down` and `up -d` |
| `password authentication failed for user "cafe"` | the app is reaching a different Postgres. Check `POSTGRES_PORT` matches `docker compose ps`, then restart uvicorn |
| `ERR_CONNECTION_RESET` in the Windows browser | start uvicorn with `--host 0.0.0.0` |
| Backend health shows `false` for postgres or redis | `docker compose ps`; restart the container, then restart uvicorn (`.env` is read at startup) |
| `ModuleNotFoundError: backend` | run from the project root with the venv active, and make sure `pip install -r requirements.txt` finished (it installs the project with `-e .`) |
| Dashboard says "Cannot reach the backend" | backend not running, or not on port 8000 |

More explanation of each part is in [learning.md](learning.md).
