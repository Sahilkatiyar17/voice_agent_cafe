"""
The menu, held in memory (see the plan's big decision: SQL is the truth, but the menu
is small enough to load into memory and also put in the prompt).

Call `await menu_cache.load()` once at API/agent startup, and again whenever the admin
edits the menu (Phase 5) so callers see changes without a restart.
"""

from decimal import Decimal

from sqlalchemy import select

from database.connection import async_session
from database.models import MenuItem
from logger import logging


class MenuCache:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.by_id: dict[int, dict] = {}

    async def load(self) -> None:
        async with async_session() as session:
            result = await session.execute(select(MenuItem))
            rows = result.scalars().all()

        self.items = [self._row_to_dict(row) for row in rows]
        self.by_id = {item["id"]: item for item in self.items}
        logging.info("Menu cache loaded: %d items", len(self.items))

    @staticmethod
    def _row_to_dict(row: MenuItem) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "category": row.category,
            "is_veg": row.is_veg,
            "price": row.price,  # Decimal - keep as Decimal internally, never float
            "aliases": row.aliases or [],
            "is_available": row.is_available,
        }

    def is_loaded(self) -> bool:
        return bool(self.items)


# Module-level singleton - one cache shared by the whole process.
menu_cache = MenuCache()


def public_item(item: dict) -> dict:
    """Shape a cached item for a tool result / the LLM: price as a plain number, not Decimal
    (Decimal doesn't JSON-encode on its own)."""
    return {
        "id": item["id"],
        "name": item["name"],
        "category": item["category"],
        "is_veg": item["is_veg"],
        "price": float(item["price"]) if isinstance(item["price"], Decimal) else item["price"],
        "is_available": item["is_available"],
    }
