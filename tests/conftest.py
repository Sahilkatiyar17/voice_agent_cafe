"""Shared pytest fixtures for the tool tests.

All test data uses call_id/phone prefixes starting with "PYTEST" so cleanup can find and
remove it precisely, and never touches the real seeded menu/tables/modifiers.
"""

import pytest_asyncio
from sqlalchemy import text

from backend.tools.menu_cache import menu_cache
from database.connection import engine

TEST_PHONE_PREFIX = "9991"  # test phone numbers all start with this
TEST_CALL_PREFIX = "PYTEST"  # test call_ids all start with this


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _load_menu_cache():
    """search_menu reads from the cache, not the DB - it must be loaded before any test runs."""
    await menu_cache.load()


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_test_rows():
    """Runs after every test, so a failed test doesn't leave junk for the next one."""
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM reservations WHERE call_id LIKE :p OR phone LIKE :ph"),
            {"p": f"{TEST_CALL_PREFIX}%", "ph": f"{TEST_PHONE_PREFIX}%"},
        )
        await conn.execute(
            text(
                "DELETE FROM order_item_modifiers WHERE order_item_id IN ("
                "  SELECT id FROM order_items WHERE order_id IN ("
                "    SELECT id FROM orders WHERE call_id LIKE :p"
                "  )"
                ")"
            ),
            {"p": f"{TEST_CALL_PREFIX}%"},
        )
        await conn.execute(
            text(
                "DELETE FROM order_items WHERE order_id IN "
                "(SELECT id FROM orders WHERE call_id LIKE :p)"
            ),
            {"p": f"{TEST_CALL_PREFIX}%"},
        )
        await conn.execute(text("DELETE FROM orders WHERE call_id LIKE :p"), {"p": f"{TEST_CALL_PREFIX}%"})
        await conn.execute(
            text("DELETE FROM addresses WHERE line1 LIKE :p"), {"p": f"{TEST_CALL_PREFIX}%"}
        )
        await conn.execute(
            text("DELETE FROM customers WHERE phone LIKE :ph"), {"ph": f"{TEST_PHONE_PREFIX}%"}
        )
