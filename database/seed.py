"""
Loads the cafe's fixed reference data: tables, menu, modifiers, and delivery pincodes.

Safe to run twice (and a hundred times): every insert is an upsert keyed on the unique
constraints added in migration 0002, so re-running just refreshes prices/names instead of
creating duplicates.

Run with:  python -m database.seed
"""

import asyncio
import sys
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from database.connection import engine
from database.models import CafeTable, DeliveryPincode, MenuItem, MenuItemModifier, Modifier
from exception import CafeException
from logger import logging

BRANCH_ID = 1

# ============================================================
# Tables (from docs/spec.md: T1-T4 seats 2, T5-T8 seats 4, T9-T10 seats 6)
# ============================================================
TABLES = (
    [{"name": f"T{i}", "seats": 2} for i in range(1, 5)]
    + [{"name": f"T{i}", "seats": 4} for i in range(5, 9)]
    + [{"name": f"T{i}", "seats": 6} for i in range(9, 11)]
)

# ============================================================
# Menu (32 items: docs/spec.md). key = spec item number, used only to link modifiers below.
# ============================================================
MENU_ITEMS = {
    # Indian
    1: dict(name="Paneer Butter Masala", category="indian", is_veg=True, price="320", aliases=["paneer makhani"]),
    2: dict(name="Palak Paneer", category="indian", is_veg=True, price="300", aliases=["saag paneer"]),
    3: dict(name="Dal Makhani", category="indian", is_veg=True, price="260", aliases=["black dal"]),
    4: dict(name="Butter Chicken", category="indian", is_veg=False, price="380", aliases=["murgh makhani"]),
    5: dict(name="Chicken Biryani", category="indian", is_veg=False, price="350", aliases=["murg biryani"]),
    6: dict(name="Veg Biryani", category="indian", is_veg=True, price="280", aliases=["vegetable biryani"]),
    7: dict(name="Butter Naan", category="indian", is_veg=True, price="60", aliases=["naan"]),
    8: dict(name="Garlic Naan", category="indian", is_veg=True, price="75", aliases=[]),
    9: dict(name="Jeera Rice", category="indian", is_veg=True, price="150", aliases=[]),
    10: dict(name="Samosa (2 pcs)", category="indian", is_veg=True, price="90", aliases=["samose"]),
    # Korean
    11: dict(name="Bibimbap (Veg)", category="korean", is_veg=True, price="340", aliases=["bibimbap"]),
    12: dict(name="Chicken Bibimbap", category="korean", is_veg=False, price="390", aliases=[]),
    13: dict(name="Kimchi Fried Rice", category="korean", is_veg=True, price="310", aliases=["kimchi rice"]),
    14: dict(name="Korean Fried Chicken (6 pcs)", category="korean", is_veg=False, price="420", aliases=["kfc", "kfc chicken"]),
    15: dict(name="Tteokbokki", category="korean", is_veg=True, price="330", aliases=["topokki", "spicy rice cakes"]),
    16: dict(name="Japchae", category="korean", is_veg=True, price="360", aliases=["glass noodles"]),
    17: dict(name="Kimchi Jjigae", category="korean", is_veg=False, price="400", aliases=["kimchi stew"]),
    18: dict(name="Korean Corn Dog", category="korean", is_veg=True, price="220", aliases=[]),
    19: dict(name="Mandu (6 pcs)", category="korean", is_veg=True, price="280", aliases=["korean dumplings", "dumplings"]),
    20: dict(name="Bulgogi Rice Bowl", category="korean", is_veg=False, price="430", aliases=["bulgogi"]),
    # Continental
    21: dict(name="Margherita Pizza", category="continental", is_veg=True, price="380", aliases=["pizza margherita"]),
    22: dict(name="Pepperoni Pizza", category="continental", is_veg=False, price="460", aliases=[]),
    23: dict(name="White Sauce Pasta", category="continental", is_veg=True, price="340", aliases=["alfredo pasta"]),
    24: dict(name="Arrabbiata Pasta", category="continental", is_veg=True, price="330", aliases=["red sauce pasta"]),
    25: dict(name="Grilled Chicken Burger", category="continental", is_veg=False, price="350", aliases=["chicken burger", "burger"]),
    26: dict(name="Veggie Burger", category="continental", is_veg=True, price="290", aliases=["veg burger", "burger"]),
    27: dict(name="Caesar Salad", category="continental", is_veg=True, price="300", aliases=[]),
    28: dict(name="French Fries", category="continental", is_veg=True, price="160", aliases=["fries"]),
    # Drinks and dessert
    29: dict(name="Masala Chai", category="drinks", is_veg=True, price="90", aliases=["chai"]),
    30: dict(name="Iced Americano", category="drinks", is_veg=True, price="180", aliases=[]),
    31: dict(name="Mango Lassi", category="drinks", is_veg=True, price="150", aliases=["lassi"]),
    32: dict(name="Brownie with Ice Cream", category="drinks", is_veg=True, price="240", aliases=["brownie"]),
}

# ============================================================
# Modifiers (docs/spec.md). group_name groups mutually-exclusive choices
# (e.g. only one spice level); None means it can be freely combined with others.
# ============================================================
MODIFIERS = {
    "spice_mild": dict(name="mild", group_name="spice", extra_price="0"),
    "spice_medium": dict(name="medium", group_name="spice", extra_price="0"),
    "spice_hot": dict(name="hot", group_name="spice", extra_price="0"),
    "no_onion": dict(name="no onion", group_name=None, extra_price="0"),
    "no_garlic": dict(name="no garlic", group_name=None, extra_price="0"),
    "extra_cheese": dict(name="extra cheese", group_name=None, extra_price="40"),
    "extra_kimchi": dict(name="extra kimchi", group_name=None, extra_price="30"),
    "add_fried_egg": dict(name="add fried egg", group_name=None, extra_price="30"),
    "extra_ice": dict(name="extra ice", group_name="ice", extra_price="0"),
    "less_ice": dict(name="less ice", group_name="ice", extra_price="0"),
    "less_sugar": dict(name="less sugar", group_name=None, extra_price="0"),
    "boneless": dict(name="boneless", group_name=None, extra_price="40"),
}

# Which modifiers apply to which menu items, by spec item number (see docs/spec.md).
SPICE_ITEMS = [1, 4, 5, 15, 17, 14, 24]
NO_ONION_GARLIC_ITEMS = [1, 2, 3, 4, 5, 6]
EXTRA_CHEESE_ITEMS = [21, 22, 23, 24, 25, 26]
EXTRA_KIMCHI_ITEMS = [11, 12, 13, 17]
FRIED_EGG_ITEMS = [11, 12, 13, 20]
ICE_ITEMS = [30, 31]
LESS_SUGAR_ITEMS = [29, 31, 32]
BONELESS_ITEMS = [4, 14]

ITEM_MODIFIER_LINKS: list[tuple[int, str]] = (
    [(i, "spice_mild") for i in SPICE_ITEMS]
    + [(i, "spice_medium") for i in SPICE_ITEMS]
    + [(i, "spice_hot") for i in SPICE_ITEMS]
    + [(i, "no_onion") for i in NO_ONION_GARLIC_ITEMS]
    + [(i, "no_garlic") for i in NO_ONION_GARLIC_ITEMS]
    + [(i, "extra_cheese") for i in EXTRA_CHEESE_ITEMS]
    + [(i, "extra_kimchi") for i in EXTRA_KIMCHI_ITEMS]
    + [(i, "add_fried_egg") for i in FRIED_EGG_ITEMS]
    + [(i, "extra_ice") for i in ICE_ITEMS]
    + [(i, "less_ice") for i in ICE_ITEMS]
    + [(i, "less_sugar") for i in LESS_SUGAR_ITEMS]
    + [(i, "boneless") for i in BONELESS_ITEMS]
)

# ============================================================
# Delivery pincodes
# STILL A PLACEHOLDER - I have no way to know the cafe's real delivery zone. What changed:
# these used to be scattered, unrelated Bengaluru pincodes; now they're a real, geographically
# coherent cluster of neighbourhoods within ~5km of CAFE_ADDRESS (backend/constant.py,
# Indiranagar), matching docs/spec.md's DELIVERY_RADIUS_KM. Still swap these for the actual
# delivery area once you have it - I picked "near Indiranagar" only because that's the
# placeholder address I gave the cafe, not because it's confirmed correct.
# ============================================================
DELIVERY_PINCODES = [
    "560038",  # Indiranagar (the cafe's own area)
    "560008",  # Ulsoor
    "560071",  # Domlur
    "560017",  # HAL / Old Airport Road
    "560075",  # Jeevanbhimanagar / HAL 2nd Stage
    "560093",  # CV Raman Nagar
]


async def seed_tables(conn: AsyncConnection) -> None:
    for table in TABLES:
        stmt = pg_insert(CafeTable).values(branch_id=BRANCH_ID, is_active=True, **table)
        stmt = stmt.on_conflict_do_update(
            index_elements=["branch_id", "name"],
            set_={"seats": stmt.excluded.seats, "is_active": stmt.excluded.is_active},
        )
        await conn.execute(stmt)
    logging.info("Seeded %d cafe_tables", len(TABLES))


async def seed_menu(conn: AsyncConnection) -> dict[int, int]:
    """Returns {spec item number: menu_items.id}."""
    item_ids: dict[int, int] = {}
    for item_no, item in MENU_ITEMS.items():
        stmt = pg_insert(MenuItem).values(
            branch_id=BRANCH_ID,
            is_available=True,
            price=Decimal(item["price"]),
            **{k: v for k, v in item.items() if k != "price"},
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["branch_id", "name"],
            set_={
                "category": stmt.excluded.category,
                "is_veg": stmt.excluded.is_veg,
                "price": stmt.excluded.price,
                "aliases": stmt.excluded.aliases,
            },
        ).returning(MenuItem.id)
        result = await conn.execute(stmt)
        item_ids[item_no] = result.scalar_one()
    logging.info("Seeded %d menu_items", len(MENU_ITEMS))
    return item_ids


async def seed_modifiers(conn: AsyncConnection) -> dict[str, int]:
    """Returns {modifier key: modifiers.id}."""
    modifier_ids: dict[str, int] = {}
    for key, mod in MODIFIERS.items():
        stmt = pg_insert(Modifier).values(extra_price=Decimal(mod["extra_price"]), **{
            k: v for k, v in mod.items() if k != "extra_price"
        })
        stmt = stmt.on_conflict_do_update(
            index_elements=["group_name", "name"],
            set_={"extra_price": stmt.excluded.extra_price},
        ).returning(Modifier.id)
        result = await conn.execute(stmt)
        modifier_ids[key] = result.scalar_one()
    logging.info("Seeded %d modifiers", len(MODIFIERS))
    return modifier_ids


async def seed_menu_item_modifiers(
    conn: AsyncConnection, item_ids: dict[int, int], modifier_ids: dict[str, int]
) -> None:
    count = 0
    for item_no, modifier_key in ITEM_MODIFIER_LINKS:
        stmt = pg_insert(MenuItemModifier).values(
            menu_item_id=item_ids[item_no], modifier_id=modifier_ids[modifier_key]
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["menu_item_id", "modifier_id"])
        await conn.execute(stmt)
        count += 1
    logging.info("Linked %d menu_item x modifier pairs", count)


async def seed_delivery_pincodes(conn: AsyncConnection) -> None:
    for pincode in DELIVERY_PINCODES:
        stmt = pg_insert(DeliveryPincode).values(pincode=pincode, branch_id=BRANCH_ID)
        stmt = stmt.on_conflict_do_nothing(index_elements=["pincode"])
        await conn.execute(stmt)
    logging.info("Seeded %d delivery_pincodes (placeholder values - edit these)", len(DELIVERY_PINCODES))


async def run() -> None:
    async with engine.begin() as conn:
        await seed_tables(conn)
        item_ids = await seed_menu(conn)
        modifier_ids = await seed_modifiers(conn)
        await seed_menu_item_modifiers(conn, item_ids, modifier_ids)
        await seed_delivery_pincodes(conn)
    logging.info("Seed complete")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as e:
        raise CafeException(e, sys) from e
