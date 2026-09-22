"""
Order tools: update_order (add/remove/change quantity), set_delivery_address,
get_order_summary, confirm_order.

Rules these TOOLS must enforce (the database cannot):
  - one modifier per group (e.g. only one spice level)
  - subtotal/delivery_fee/total are recomputed from the order_items lines on every change,
    never patched by hand (see database/models.py docstring)
  - is_available is re-checked at confirm_order, not just when the item was added
  - confirm_order is idempotent and safe to call twice
"""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from backend.constant import DELIVERY_FEE, FREE_DELIVERY_ABOVE, MIN_ORDER_VALUE
from database.connection import async_session
from database.models import (
    ORDER_CONFIRMED,
    ORDER_DRAFT,
    Address,
    Customer,
    DeliveryPincode,
    MenuItem,
    MenuItemModifier,
    Modifier,
    Order,
    OrderItem,
    OrderItemModifier,
)
from logger import logging

UTC = ZoneInfo("UTC")
BRANCH_ID = 1


# ============================================================
# internal helpers
# ============================================================

async def _get_or_create_draft_order(session, order_id: int | None, call_id: str | None) -> Order:
    if order_id is not None:
        order = await session.get(Order, order_id)
        if order is None:
            raise ValueError("No such order.")
        if order.status != ORDER_DRAFT:
            raise ValueError(f"Order is '{order.status}', not a draft - can't modify.")
        return order

    if call_id:
        existing = (
            await session.execute(
                select(Order).where(Order.call_id == call_id, Order.status == ORDER_DRAFT)
            )
        ).scalars().first()
        if existing:
            return existing

    order = Order(branch_id=BRANCH_ID, call_id=call_id, status=ORDER_DRAFT)
    session.add(order)
    await session.flush()
    return order


async def _validate_modifiers(session, menu_item_id: int, modifier_ids: list[int]) -> list[Modifier]:
    """Checks the modifiers exist, apply to this item, and don't collide (two picks from
    the same group, e.g. two spice levels)."""
    if not modifier_ids:
        return []

    modifiers = (
        await session.execute(select(Modifier).where(Modifier.id.in_(modifier_ids)))
    ).scalars().all()
    missing = set(modifier_ids) - {m.id for m in modifiers}
    if missing:
        raise ValueError(f"Unknown modifier id(s): {sorted(missing)}")

    allowed_ids = set(
        (
            await session.execute(
                select(MenuItemModifier.modifier_id).where(
                    MenuItemModifier.menu_item_id == menu_item_id
                )
            )
        )
        .scalars()
        .all()
    )
    not_allowed = [m for m in modifiers if m.id not in allowed_ids]
    if not_allowed:
        names = ", ".join(m.name for m in not_allowed)
        raise ValueError(f"These modifiers don't apply to this item: {names}")

    seen_groups: dict[str, str] = {}
    for m in modifiers:
        if m.group_name:
            if m.group_name in seen_groups:
                raise ValueError(
                    f"Only one '{m.group_name}' option is allowed "
                    f"(picked both '{seen_groups[m.group_name]}' and '{m.name}')."
                )
            seen_groups[m.group_name] = m.name

    return modifiers


async def _recalculate_order(session, order_id: int) -> Order:
    """The single place order totals are computed - always from the lines, never patched
    by hand. Delivery fee: free above FREE_DELIVERY_ABOVE, 0 for an empty order."""
    subtotal_raw = (
        await session.execute(
            select(func.coalesce(func.sum(OrderItem.line_total), 0)).where(
                OrderItem.order_id == order_id
            )
        )
    ).scalar_one()
    subtotal = Decimal(subtotal_raw)

    if subtotal <= 0 or subtotal >= Decimal(str(FREE_DELIVERY_ABOVE)):
        delivery_fee = Decimal("0")
    else:
        delivery_fee = Decimal(str(DELIVERY_FEE))

    total = subtotal + delivery_fee
    await session.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(subtotal=subtotal, delivery_fee=delivery_fee, total=total)
    )
    return await session.get(Order, order_id)


def _order_totals(order: Order) -> dict:
    return {
        "order_id": order.id,
        "subtotal": float(order.subtotal),
        "delivery_fee": float(order.delivery_fee),
        "total": float(order.total),
    }


# ============================================================
# add / remove / change quantity
# ============================================================

async def add_item(
    order_id: int | None,
    call_id: str | None,
    menu_item_id: int,
    quantity: int = 1,
    modifier_ids: list[int] | None = None,
) -> dict:
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")

    async with async_session() as session:
        order = await _get_or_create_draft_order(session, order_id, call_id)

        item = await session.get(MenuItem, menu_item_id)
        if item is None:
            raise ValueError("No such menu item.")
        if not item.is_available:
            raise ValueError(f"{item.name} is sold out right now.")

        modifiers = await _validate_modifiers(session, menu_item_id, modifier_ids or [])
        modifier_total = sum((m.extra_price for m in modifiers), Decimal("0"))
        line_total = (item.price + modifier_total) * quantity

        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=item.id,
            item_name=item.name,
            unit_price=item.price,
            quantity=quantity,
            line_total=line_total,
        )
        session.add(order_item)
        await session.flush()

        for m in modifiers:
            session.add(
                OrderItemModifier(
                    order_item_id=order_item.id,
                    modifier_id=m.id,
                    modifier_name=m.name,
                    extra_price=m.extra_price,
                )
            )
        await session.flush()

        updated_order = await _recalculate_order(session, order.id)
        await session.commit()
        logging.info("Added %s x%d to order %s", item.name, quantity, order.id)
        return {"order_item_id": order_item.id, **_order_totals(updated_order)}


async def remove_item(order_id: int, order_item_id: int) -> dict:
    async with async_session() as session:
        order = await session.get(Order, order_id)
        if order is None:
            raise ValueError("No such order.")
        if order.status != ORDER_DRAFT:
            raise ValueError(f"Order is '{order.status}', not a draft - can't modify.")

        order_item = await session.get(OrderItem, order_item_id)
        if order_item is None or order_item.order_id != order_id:
            raise ValueError("No such item on this order.")

        await session.delete(order_item)
        await session.flush()

        updated_order = await _recalculate_order(session, order.id)
        await session.commit()
        logging.info("Removed order_item %s from order %s", order_item_id, order_id)
        return _order_totals(updated_order)


async def set_quantity(order_id: int, order_item_id: int, quantity: int) -> dict:
    """quantity == 0 removes the item (covers "actually remove the burger")."""
    if quantity < 0:
        raise ValueError("Quantity can't be negative.")
    if quantity == 0:
        return await remove_item(order_id, order_item_id)

    async with async_session() as session:
        order = await session.get(Order, order_id)
        if order is None:
            raise ValueError("No such order.")
        if order.status != ORDER_DRAFT:
            raise ValueError(f"Order is '{order.status}', not a draft - can't modify.")

        order_item = await session.get(OrderItem, order_item_id)
        if order_item is None or order_item.order_id != order_id:
            raise ValueError("No such item on this order.")

        modifier_total_raw = (
            await session.execute(
                select(func.coalesce(func.sum(OrderItemModifier.extra_price), 0)).where(
                    OrderItemModifier.order_item_id == order_item_id
                )
            )
        ).scalar_one()

        order_item.quantity = quantity
        order_item.line_total = (order_item.unit_price + Decimal(modifier_total_raw)) * quantity
        await session.flush()

        updated_order = await _recalculate_order(session, order.id)
        await session.commit()
        return _order_totals(updated_order)


async def update_order(
    action: str,
    order_id: int | None = None,
    call_id: str | None = None,
    menu_item_id: int | None = None,
    order_item_id: int | None = None,
    quantity: int = 1,
    modifier_ids: list[int] | None = None,
) -> dict:
    """Single entry point matching the plan's tool list. action: 'add_item',
    'remove_item', or 'set_quantity'."""
    if action == "add_item":
        if menu_item_id is None:
            raise ValueError("menu_item_id is required to add an item.")
        return await add_item(order_id, call_id, menu_item_id, quantity, modifier_ids)
    if action == "remove_item":
        if order_id is None or order_item_id is None:
            raise ValueError("order_id and order_item_id are required to remove an item.")
        return await remove_item(order_id, order_item_id)
    if action == "set_quantity":
        if order_id is None or order_item_id is None:
            raise ValueError("order_id and order_item_id are required to set quantity.")
        return await set_quantity(order_id, order_item_id, quantity)
    raise ValueError(f"Unknown action '{action}'. Use add_item, remove_item, or set_quantity.")


# ============================================================
# address, summary, confirm
# ============================================================

async def set_delivery_address(
    order_id: int,
    phone: str,
    line1: str,
    pincode: str,
    name: str | None = None,
    landmark: str | None = None,
) -> dict:
    async with async_session() as session:
        order = await session.get(Order, order_id)
        if order is None:
            raise ValueError("No such order.")
        if order.status != ORDER_DRAFT:
            raise ValueError(f"Order is '{order.status}', not a draft - can't modify.")

        in_area = (
            await session.execute(
                select(DeliveryPincode).where(
                    DeliveryPincode.pincode == pincode, DeliveryPincode.branch_id == BRANCH_ID
                )
            )
        ).scalars().first()
        if in_area is None:
            raise ValueError(f"Sorry, we don't deliver to {pincode}.")

        stmt = pg_insert(Customer).values(phone=phone, name=name)
        stmt = stmt.on_conflict_do_update(
            index_elements=["phone"],
            set_={"name": func.coalesce(stmt.excluded.name, Customer.name)},
        ).returning(Customer.id)
        customer_id = (await session.execute(stmt)).scalar_one()

        address = Address(customer_id=customer_id, line1=line1, landmark=landmark, pincode=pincode)
        session.add(address)
        await session.flush()

        order.customer_id = customer_id
        order.address_id = address.id
        await session.commit()
        logging.info("Set delivery address for order %s", order_id)
        return {"order_id": order.id, "address_id": address.id}


async def get_order_summary(order_id: int) -> dict:
    async with async_session() as session:
        order = (
            await session.execute(
                select(Order)
                .options(selectinload(Order.items).selectinload(OrderItem.modifiers))
                .where(Order.id == order_id)
            )
        ).scalar_one_or_none()
        if order is None:
            raise ValueError("No such order.")

        return {
            "order_id": order.id,
            "status": order.status,
            "items": [
                {
                    "order_item_id": oi.id,
                    "name": oi.item_name,
                    "quantity": oi.quantity,
                    "unit_price": float(oi.unit_price),
                    "modifiers": [m.modifier_name for m in oi.modifiers],
                    "line_total": float(oi.line_total),
                }
                for oi in order.items
            ],
            "subtotal": float(order.subtotal),
            "delivery_fee": float(order.delivery_fee),
            "total": float(order.total),
            "address_id": order.address_id,
        }


async def confirm_order(order_id: int) -> dict:
    """Idempotent, and re-checks availability + minimum order inside the transaction -
    a sold-out flip or a stale total since add_item must not silently go through."""
    async with async_session() as session:
        order = (
            await session.execute(
                select(Order)
                .options(selectinload(Order.items))
                .where(Order.id == order_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise ValueError("No such order.")

        if order.status == ORDER_CONFIRMED:
            return {"confirmed": True, "order_id": order.id, "total": float(order.total)}
        if order.status != ORDER_DRAFT:
            raise ValueError(f"Order is '{order.status}' - can't confirm.")

        if not order.items:
            raise ValueError("Can't confirm an empty order.")
        if order.address_id is None:
            raise ValueError("Set a delivery address before confirming.")

        menu_item_ids = [oi.menu_item_id for oi in order.items if oi.menu_item_id is not None]
        unavailable = (
            await session.execute(
                select(MenuItem.name).where(
                    MenuItem.id.in_(menu_item_ids), MenuItem.is_available.is_(False)
                )
            )
        ).scalars().all()
        if unavailable:
            raise ValueError(
                f"No longer available: {', '.join(unavailable)}. Remove or swap before confirming."
            )

        updated_order = await _recalculate_order(session, order.id)
        if updated_order.subtotal < Decimal(str(MIN_ORDER_VALUE)):
            raise ValueError(
                f"Minimum order is Rs {MIN_ORDER_VALUE} (currently Rs {updated_order.subtotal})."
            )

        updated_order.status = ORDER_CONFIRMED
        updated_order.confirmed_at = datetime.now(UTC)
        await session.commit()
        logging.info("Confirmed order %s", order.id)
        return {"confirmed": True, "order_id": order.id, "total": float(updated_order.total)}
