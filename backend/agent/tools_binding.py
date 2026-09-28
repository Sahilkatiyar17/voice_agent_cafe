"""
Wraps every Phase 2 tool as a LangChain tool the graph's ToolNode can call.

Two rules drive every wrapper here:

1. order_id/reservation_id/call_id are NEVER parameters the LLM can supply. They live on
   the SessionRef this module closes over, and each wrapper reads/writes them directly.
   If a tool's real signature needs order_id, the wrapped version simply doesn't expose
   it - the model has no way to guess or hallucinate one. (cancel_reservation is the one
   deliberate exception: a caller may want to cancel a DIFFERENT reservation than the
   one currently held in this session, found via lookup_reservation, so it stays an
   explicit argument.)

2. Docstrings here are read by the model as the tool's description (that's how LangChain's
   @tool decorator works), so they're written as instructions to follow, not just
   descriptions of what the function does.

Error handling: a tool raising ValueError (Phase 2's convention for an expected domain
error - sold out, wrong pincode, no such reservation, ...) is caught by LangGraph's
prebuilt ToolNode automatically and turned into an error ToolMessage fed back to the
model, so it can explain the problem and ask what to do next instead of crashing the
whole conversation. That default needs no extra code here. The _call() helper below only
adds one thing on top: if something genuinely unexpected happens (a DB connection drop,
a bug), it's still logged with file/line via CafeException before propagating - ToolNode
still catches it the same way, this just keeps the log breadcrumb Phase 2 relies on
everywhere else.
"""

import sys
from typing import Callable

from langchain_core.tools import tool
from pydantic import BaseModel

from backend.agent import formatting as fmt
from backend.agent.session import SessionRef
from backend.tools import orders as ord
from backend.tools import reservations as res
from backend.tools import search_menu as search_menu_module
from backend.tools.business_info import get_business_info as get_business_info_fn
from exception import CafeException
from logger import logging


async def _call(fn: Callable, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except ValueError:
        raise  # expected domain error - let ToolNode turn this into an error ToolMessage
    except Exception as e:
        logging.error("Unexpected error in tool %s: %s", getattr(fn, "__name__", fn), e)
        raise CafeException(e, sys) from e


class OrderItemInput(BaseModel):
    """One line for the batched add_item tool - a plain dict would give the model a
    vaguer schema; this gives it a proper structured shape for each list entry."""

    menu_item_id: int
    quantity: int = 1
    modifier_ids: list[int] | None = None


def make_tools(session: SessionRef) -> list:
    """Builds one tool list per conversation, closing over `session` so every wrapper
    below can read/write its order_id and reservation_id."""

    # ---------------- menu ----------------

    @tool
    def search_menu(queries: list[str]) -> str:
        """Look up menu items by name (e.g. "chicken biryani", "burger"). ALWAYS call this
        before quoting a price or availability, and before add_item - never guess a
        menu_item_id or price from memory, even from the menu list in your instructions;
        that list can go a few minutes stale, this tool cannot.

        If the caller names several items in one sentence ("I'll have a biryani, a naan,
        and a lassi"), pass ALL of them here in ONE call as a list - never call this once
        per item, that wastes a full round trip for each one. You can still call it again
        afterwards with just one query if a single result came back ambiguous and you need
        to re-check it after asking the caller a clarifying question.

        Each result line is "<your query>" -> <outcome>: "Exact match" (use that #id
        directly), "Not an exact match" / "No match found" with options (ask which one, or
        offer them), or "No matching item found" (say so)."""
        results = [(q, search_menu_module.search_menu(q)) for q in queries]
        return fmt.format_search_menu_batch(results)

    # ---------------- reservations ----------------

    @tool
    async def check_availability(date: str, time: str, party_size: int) -> str:
        """Check whether a table is free. date is 'YYYY-MM-DD', time is 24-hour 'HH:MM',
        both in the cafe's local time. Call this before hold_slot so you can tell the
        caller right away if nothing is free for what they asked."""
        return fmt.format_check_availability(await _call(res.check_availability, date, time, party_size))

    @tool
    async def hold_slot(date: str, time: str, party_size: int, customer_name: str, phone: str) -> str:
        """Tentatively hold a table for 5 minutes. Only call this once the caller has
        given you date, time, party size, their name, AND their phone number - ask for
        whichever of these you're missing, one at a time, don't ask for two at once. This
        is just a hold, not a booking yet - it doesn't need caller confirmation first,
        but confirm_reservation does."""
        result = await _call(res.hold_slot, date, time, party_size, customer_name, phone, call_id=session.call_id)
        if result.get("reservation_id"):
            session.reservation_id = result["reservation_id"]
            logging.info("[%s] session.reservation_id = %s", session.call_id, session.reservation_id)
        return fmt.format_hold_slot(result)

    @tool
    async def confirm_reservation() -> str:
        """Finalize the currently held reservation. ONLY call this after you've read the
        date, time, party size, and table back to the caller AND they've clearly said
        yes - "yes", "that's right", "confirm it". Never call this on an implicit or
        assumed yes."""
        if session.reservation_id is None:
            raise ValueError("No reservation is on hold yet - call hold_slot first.")
        return fmt.format_confirm_reservation(await _call(res.confirm_reservation, session.reservation_id))

    @tool
    async def cancel_reservation(reservation_id: int) -> str:
        """Cancel a reservation by its id - from lookup_reservation, or from a hold you
        just made in this call. Confirm with the caller before calling this."""
        return fmt.format_cancel_reservation(await _call(res.cancel_reservation, reservation_id))

    @tool
    async def lookup_reservation(phone: str | None = None, reservation_id: int | None = None) -> str:
        """Find a caller's past or current reservations by phone number or id - e.g. when
        they ask "what happened to my booking?" Shows every status, including cancelled
        and expired ones, not just active bookings."""
        result = await _call(res.lookup_reservation, phone=phone, reservation_id=reservation_id)
        return fmt.format_lookup_reservation(result)

    # ---------------- orders ----------------

    @tool
    async def add_item(items: list[OrderItemInput]) -> str:
        """Add one or more items to the current draft order (creating one if this call
        doesn't have one yet), in a SINGLE call. If the caller named several items in one
        sentence ("a biryani, a naan, and a lassi"), pass all of them here as separate
        entries in the list - never call this once per item, that wastes a full round trip
        for each one. Get each menu_item_id from search_menu's result FIRST - never guess
        an id or invent one from the menu shown in your instructions. modifier_ids are
        optional (e.g. spice level) - ask if relevant to an item, don't assume a default.

        If one item fails (e.g. sold out), the others still get added - the result lists
        which succeeded and which didn't, one line per item, so you can tell the caller
        about the failure and ask what to do, without losing the rest of the order."""
        lines = []
        last_success = None
        for item in items:
            try:
                result = await _call(
                    ord.add_item, session.order_id, session.call_id,
                    item.menu_item_id, item.quantity, item.modifier_ids,
                )
            except ValueError as e:
                lines.append(f"#{item.menu_item_id}: failed - {e}")
                continue
            if session.order_id != result["order_id"]:  # first successful item - a draft order was just created
                session.order_id = result["order_id"]
                logging.info("[%s] session.order_id = %s", session.call_id, session.order_id)
            lines.append(f"#{item.menu_item_id} x{item.quantity}: added (line #{result['order_item_id']})")
            last_success = result
        return fmt.format_add_item_batch(lines, last_success)

    @tool
    async def remove_item(order_item_id: int) -> str:
        """Remove one line from the current order. order_item_id comes from
        get_order_summary or from a previous add_item result - never guess it."""
        if session.order_id is None:
            raise ValueError("There is no order yet for this call.")
        return fmt.format_remove_item(await _call(ord.remove_item, session.order_id, order_item_id))

    @tool
    async def set_item_quantity(order_item_id: int, quantity: int) -> str:
        """Change how many of one item are in the order. quantity 0 removes it entirely -
        use this for "actually make that two" or "remove the burger"."""
        if session.order_id is None:
            raise ValueError("There is no order yet for this call.")
        result = await _call(ord.set_quantity, session.order_id, order_item_id, quantity)
        return fmt.format_set_item_quantity(result)

    @tool
    async def cancel_order() -> str:
        """Cancel the whole current order - use this if the caller says something like
        "never mind, forget it" or wants to start over. Only works while the order is
        still a draft (not yet confirmed)."""
        if session.order_id is None:
            raise ValueError("There is no order yet for this call.")
        return fmt.format_cancel_order(await _call(ord.cancel_order, session.order_id))

    @tool
    async def set_delivery_address(
        phone: str, line1: str, pincode: str, name: str | None = None, landmark: str | None = None
    ) -> str:
        """Set the delivery address for the current order. Ask for phone, the address
        line, and the pincode if you don't already have them. This will fail if the
        pincode is outside the delivery area - if it does, tell the caller plainly and
        ask what they'd like to do, don't retry silently or guess a nearby pincode."""
        if session.order_id is None:
            raise ValueError("Add at least one item before setting a delivery address.")
        result = await _call(ord.set_delivery_address, session.order_id, phone, line1, pincode, name, landmark)
        return fmt.format_set_delivery_address(result)

    @tool
    async def get_order_summary() -> str:
        """Get the full current order - items, subtotal, delivery fee, total, and whether
        an address is set. Call this to read the order back to the caller before
        confirming - never recite totals from memory, they may be stale."""
        if session.order_id is None:
            raise ValueError("There is no order yet for this call.")
        return fmt.format_get_order_summary(await _call(ord.get_order_summary, session.order_id))

    @tool
    async def confirm_order() -> str:
        """Finalize the order. ONLY call this after reading back every item and the total
        and the caller has clearly said yes. This re-checks the minimum order value and
        that every item is still available - if it fails, explain the problem plainly and
        ask what the caller wants to change, don't guess or retry silently."""
        if session.order_id is None:
            raise ValueError("There is no order yet for this call.")
        return fmt.format_confirm_order(await _call(ord.confirm_order, session.order_id))

    # ---------------- info ----------------

    @tool
    def get_business_info() -> str:
        """Hours, delivery area, minimum order, and payment method. Most of this is
        already in your instructions - only call this if you're unsure, or the caller
        asks something you can't confidently answer from what you already know."""
        return fmt.format_get_business_info(get_business_info_fn())

    return [
        search_menu,
        check_availability,
        hold_slot,
        confirm_reservation,
        cancel_reservation,
        lookup_reservation,
        add_item,
        remove_item,
        set_item_quantity,
        cancel_order,
        set_delivery_address,
        get_order_summary,
        confirm_order,
        get_business_info,
    ]
