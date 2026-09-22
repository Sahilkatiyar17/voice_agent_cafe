from fastapi import APIRouter

from backend.api.errors import handle_tool_errors
from backend.api.schemas import AddItemRequest, SetAddressRequest, SetQuantityRequest
from backend.tools.orders import (
    add_item,
    confirm_order,
    get_order_summary,
    remove_item,
    set_delivery_address,
    set_quantity,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/items")
@handle_tool_errors
async def add_item_endpoint(body: AddItemRequest):
    return await add_item(
        body.order_id, body.call_id, body.menu_item_id, body.quantity, body.modifier_ids
    )


@router.patch("/{order_id}/items/{order_item_id}")
@handle_tool_errors
async def set_quantity_endpoint(order_id: int, order_item_id: int, body: SetQuantityRequest):
    return await set_quantity(order_id, order_item_id, body.quantity)


@router.delete("/{order_id}/items/{order_item_id}")
@handle_tool_errors
async def remove_item_endpoint(order_id: int, order_item_id: int):
    return await remove_item(order_id, order_item_id)


@router.post("/{order_id}/address")
@handle_tool_errors
async def set_address_endpoint(order_id: int, body: SetAddressRequest):
    return await set_delivery_address(
        order_id, body.phone, body.line1, body.pincode, body.name, body.landmark
    )


@router.get("/{order_id}")
@handle_tool_errors
async def get_order_endpoint(order_id: int):
    return await get_order_summary(order_id)


@router.post("/{order_id}/confirm")
@handle_tool_errors
async def confirm_order_endpoint(order_id: int):
    return await confirm_order(order_id)
