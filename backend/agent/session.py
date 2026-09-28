"""
SessionRef: one instance per call, holding the internal database ids the LLM must never
invent or track itself - the same "rules live in code, not the prompt" principle behind
search_menu deciding menu matches in Phase 2. Tools in tools_binding.py close over one of
these and read/write it directly, so the model only ever supplies what a caller would
actually say out loud (a date, a phone number, an item name) - never a raw order_id or
reservation_id.
"""

import sys
from dataclasses import dataclass, field
from datetime import date

from backend.tools.clock import get_today
from backend.tools.orders import get_order_summary
from backend.tools.reservations import lookup_reservation
from exception import CafeException


@dataclass
class SessionRef:
    call_id: str
    order_id: int | None = None
    reservation_id: int | None = None
    # The cafe's date, loaded once at the moment the session is created (default_factory
    # runs then). So it's fresh for every call, and a backend left running for days never
    # serves a stale date. Read by prompts.build_system_prompt; the LLM never controls it.
    today: date = field(default_factory=get_today)


async def render_call_sheet(session: SessionRef) -> str:
    """
    A short, live summary of where this call stands right now. Rebuilt fresh from the
    database on every turn (never cached) - this is what the plan means by "show the
    state to the LLM as a small call sheet each turn": the model never has to remember
    totals or item lists from earlier in the conversation, it gets read the current truth.

    Both ids on `session` came from a tool call that already succeeded, so a failure to
    read them back (even a ValueError like "No such order") means something is genuinely
    wrong - not an expected domain error the caller could fix. It's wrapped in
    CafeException so it's logged with file and line, and left to crash loudly.
    """
    try:
        parts: list[str] = []

        if session.reservation_id is not None:
            lookup = await lookup_reservation(reservation_id=session.reservation_id)
            if lookup["reservations"]:
                r = lookup["reservations"][0]
                parts.append(
                    f"Reservation #{r['id']}: {r['party_size']} people at {r['starts_at']} "
                    f"({r['status']})"
                )

        if session.order_id is not None:
            summary = await get_order_summary(session.order_id)
            if summary["items"]:
                items_str = "; ".join(f"{i['quantity']}x {i['name']}" for i in summary["items"])
            else:
                items_str = "no items yet"
            address = "set" if summary["address_id"] else "not set"
            parts.append(
                f"Order #{summary['order_id']} ({summary['status']}): {items_str} - "
                f"subtotal Rs{summary['subtotal']}, delivery Rs{summary['delivery_fee']}, "
                f"total Rs{summary['total']}, address {address}"
            )

        return "\n".join(parts) if parts else "(no active order or reservation yet)"
    except Exception as e:
        raise CafeException(e, sys) from e
