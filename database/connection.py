from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import settings
from logger import logging

# pool_size/max_overflow above SQLAlchemy's default (5 + 10): a real phone system will have
# several calls active at once, each holding its own session for the length of a tool call.
engine = create_async_engine(settings.database_url, pool_size=20, max_overflow=20)
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
