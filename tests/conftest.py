"""Shared pytest fixtures for the tool tests.

All test data uses call_id/phone prefixes starting with "PYTEST" so cleanup can find and
remove it precisely, and never touches the real seeded menu/tables/modifiers.

Tests that never touch the database (pure logic: endpointing, formatting, LLM config) mark
their module with `pytestmark = pytest.mark.no_db`. They then skip the database setup and
cleanup below, so they run even when Postgres is down.
"""

import pytest_asyncio
from sqlalchemy import text

from backend.tools.menu_cache import menu_cache
from database.connection import engine

TEST_PHONE_PREFIX = "9991"  # test phone numbers all start with this
TEST_CALL_PREFIX = "PYTEST"  # test call_ids all start with this


@pytest_asyncio.fixture(autouse=True)
async def _database(request):
    """Before a database test: make sure the menu cache is loaded (search_menu reads the
    cache, not the DB). After it: delete whatever test rows it created, so a failed test
    doesn't leave junk for the next one. Skipped entirely for `no_db` tests."""
    if request.node.get_closest_marker("no_db"):
        yield
        return

    if not menu_cache.is_loaded():  # once per test session, on the first DB test
        await menu_cache.load()
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
