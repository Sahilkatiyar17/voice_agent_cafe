from fastapi import APIRouter, Query

from backend.api.errors import handle_tool_errors
from backend.api.schemas import CheckAvailabilityRequest, HoldSlotRequest
from backend.tools.reservations import (
    cancel_reservation,
    check_availability,
    confirm_reservation,
    hold_slot,
    lookup_reservation,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.post("/check-availability")
@handle_tool_errors
async def check_availability_endpoint(body: CheckAvailabilityRequest):
    return await check_availability(body.date, body.time, body.party_size)


@router.post("/hold")
@handle_tool_errors
async def hold_slot_endpoint(body: HoldSlotRequest):
    return await hold_slot(
        body.date, body.time, body.party_size, body.customer_name, body.phone, body.call_id
    )


@router.post("/{reservation_id}/confirm")
@handle_tool_errors
async def confirm_reservation_endpoint(reservation_id: int):
    return await confirm_reservation(reservation_id)


@router.post("/{reservation_id}/cancel")
@handle_tool_errors
async def cancel_reservation_endpoint(reservation_id: int):
    return await cancel_reservation(reservation_id)


@router.get("/lookup")
@handle_tool_errors
async def lookup_reservation_endpoint(
    phone: str | None = Query(default=None),
    reservation_id: int | None = Query(default=None),
):
    return await lookup_reservation(phone=phone, reservation_id=reservation_id)
