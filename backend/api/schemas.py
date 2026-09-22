"""Request bodies for the tool-backed endpoints. Kept separate from database/models.py -
these describe what a caller sends over HTTP, not what's stored."""

from pydantic import BaseModel


class CheckAvailabilityRequest(BaseModel):
    date: str  # "2026-10-01"
    time: str  # "19:30", 24-hour
    party_size: int


class HoldSlotRequest(BaseModel):
    date: str
    time: str
    party_size: int
    customer_name: str
    phone: str
    call_id: str | None = None


class AddItemRequest(BaseModel):
    order_id: int | None = None
    call_id: str | None = None
    menu_item_id: int
    quantity: int = 1
    modifier_ids: list[int] | None = None


class SetQuantityRequest(BaseModel):
    quantity: int


class SetAddressRequest(BaseModel):
    phone: str
    line1: str
    pincode: str
    name: str | None = None
    landmark: str | None = None
