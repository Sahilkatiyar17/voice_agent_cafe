import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import business, menu, orders, reservations
from backend.constant import API_TITLE, CORS_ORIGINS
from backend.tools.menu_cache import menu_cache
from database.connection import check_postgres, check_redis
from exception import CafeException
from logger import logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    # search_menu reads from this cache, not the DB, on every call - it must be loaded
    # before any request comes in.
    await menu_cache.load()
    yield


app = FastAPI(title=API_TITLE, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(menu.router)
app.include_router(reservations.router)
app.include_router(orders.router)
app.include_router(business.router)


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
