from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import settings
from logger import logging

engine = create_async_engine(settings.database_url)
# Usage: async with async_session() as session: ...
async_session = async_sessionmaker(engine, expire_on_commit=False)
redis_client = Redis.from_url(settings.redis_url)


async def check_postgres() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logging.error("Postgres check failed: %s", e)
        return False


async def check_redis() -> bool:
    try:
        return bool(await redis_client.ping())
    except Exception as e:
        logging.error("Redis check failed: %s", e)
        return False
