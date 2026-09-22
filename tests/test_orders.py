"""Order tools: modifiers/totals math, address validation, minimum order, the sold-out
recheck at confirm time, and confirm_order's idempotency."""

import pytest
from sqlalchemy import select

from backend.tools.orders import (
    add_item,
    confirm_order,
    set_delivery_address,
    update_order,
)
from database.connection import async_session
from database.models import MenuItem, Modifier
from tests.conftest import TEST_PHONE_PREFIX

pytestmark = pytest.mark.asyncio


async def _get_by_name(model, name: str):
    async with async_session() as session:
        return (await session.execute(select(model).where(model.name == name))).scalar_one()


async def test_add_item_with_modifiers_computes_total():
    butter_chicken = await _get_by_name(MenuItem, "Butter Chicken")
    hot = await _get_by_name(Modifier, "hot")
    no_onion = await _get_by_name(Modifier, "no onion")

    result = await add_item(
        None, "PYTEST_ORDER1", butter_chicken.id, quantity=1, modifier_ids=[hot.id, no_onion.id]
    )
    # both modifiers are free (extra_price=0), so subtotal is just the item price
    assert result["subtotal"] == 380.0


async def test_two_modifiers_from_the_same_group_is_rejected():
    # Butter Chicken is one of the items spice levels actually apply to (docs/spec.md);
    # Butter Naan isn't, which would fail for the wrong reason ("doesn't apply to this item").
    butter_chicken = await _get_by_name(MenuItem, "Butter Chicken")
    mild = await _get_by_name(Modifier, "mild")
    hot = await _get_by_name(Modifier, "hot")

    with pytest.raises(ValueError, match="spice"):
        await add_item(None, "PYTEST_ORDER2", butter_chicken.id, modifier_ids=[mild.id, hot.id])


async def test_set_quantity_recomputes_subtotal():
    naan = await _get_by_name(MenuItem, "Butter Naan")
    add_result = await add_item(None, "PYTEST_ORDER3", naan.id, quantity=1)
    order_id = add_result["order_id"]
    order_item_id = add_result["order_item_id"]

    qty_result = await update_order("set_quantity", order_id=order_id, order_item_id=order_item_id, quantity=3)
    assert qty_result["subtotal"] == 180.0  # 60 * 3

    zero_result = await update_order("set_quantity", order_id=order_id, order_item_id=order_item_id, quantity=0)
    assert zero_result["subtotal"] == 0.0  # quantity 0 removes the line entirely


async def test_delivery_address_rejects_out_of_area_pincode():
    naan = await _get_by_name(MenuItem, "Butter Naan")
    add_result = await add_item(None, "PYTEST_ORDER4", naan.id, quantity=1)

    with pytest.raises(ValueError, match="deliver"):
        await set_delivery_address(
            add_result["order_id"], f"{TEST_PHONE_PREFIX}0010", "PYTEST test address", "000000"
        )


async def test_confirm_order_enforces_minimum_order_value():
    naan = await _get_by_name(MenuItem, "Butter Naan")
    add_result = await add_item(None, "PYTEST_ORDER5", naan.id, quantity=1)  # Rs 60, below Rs 250 minimum
    await set_delivery_address(
        add_result["order_id"], f"{TEST_PHONE_PREFIX}0011", "PYTEST test address", "560038"
    )

    with pytest.raises(ValueError, match="Minimum order"):
        await confirm_order(add_result["order_id"])


async def test_confirm_order_succeeds_and_is_idempotent():
    butter_chicken = await _get_by_name(MenuItem, "Butter Chicken")  # Rs 380, clears the minimum
    add_result = await add_item(None, "PYTEST_ORDER6", butter_chicken.id, quantity=1)
    await set_delivery_address(
        add_result["order_id"], f"{TEST_PHONE_PREFIX}0012", "PYTEST test address", "560038"
    )

    first = await confirm_order(add_result["order_id"])
    assert first["confirmed"]
    assert first["total"] == 420.0  # 380 + Rs 40 delivery fee (subtotal < Rs 700 free threshold)

    second = await confirm_order(add_result["order_id"])
    assert second["confirmed"]
    assert second["total"] == first["total"]  # calling it twice doesn't re-charge or change anything


async def test_confirm_order_blocks_a_sold_out_item():
    butter_chicken = await _get_by_name(MenuItem, "Butter Chicken")
    naan = await _get_by_name(MenuItem, "Butter Naan")

    add_result = await add_item(None, "PYTEST_ORDER7", butter_chicken.id, quantity=2)  # Rs 760, clears minimum

    async with async_session() as session:
        item = await session.get(MenuItem, naan.id)
        item.is_available = False
        await session.commit()
    try:
        with pytest.raises(ValueError, match="sold out"):
            await add_item(add_result["order_id"], None, naan.id, quantity=1)
    finally:
        async with async_session() as session:
            item = await session.get(MenuItem, naan.id)
            item.is_available = True
            await session.commit()
