import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.constant import API_TITLE, CORS_ORIGINS
from database.connection import check_postgres, check_redis
from exception import CafeException
from logger import logging

app = FastAPI(title=API_TITLE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Checks that both Postgres and Redis answer."""
    try:
        status = {
            "postgres": await check_postgres(),
            "redis": await check_redis(),
        }
        ok = all(status.values())
        if ok:
            logging.info("Health check passed: %s", status)
        else:
            logging.warning("Health check failed: %s", status)
        return {"ok": ok, **status}
    except Exception as e:
        raise CafeException(e, sys) from e
