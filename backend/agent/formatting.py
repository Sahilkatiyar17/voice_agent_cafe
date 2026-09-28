"""
Turns a tool's result dict into a short sentence for the model to read, instead of the
raw JSON. Every function here is pure - no async, no DB, no LLM call - so this whole file
is free to test.

Why this exists: whatever a tool's ToolMessage content is becomes part of the
conversation history, and gets resent to Groq on every later turn for as long as the
conversation lasts. A raw dict like
    {"status": "exact", "item": {"id": 5, "name": "Chicken Biryani", ...}, "suggestions": []}
costs noticeably more tokens, forever, than the same information as a sentence.

The rule for what each formatter keeps: anything the model might need to name in a LATER
tool call (an id, mainly) stays in the text. Anything that's only useful once, right now
(a full nested dict shape, a null suggestions list) gets dropped.

Errors need no formatter here - see graph.py's _domain_error_message: a ValueError's
`str(e)` is already just the bare message, never JSON.
"""

def _money(value) -> str:
    """450.0 -> '450', 450.5 -> '450.50' - Rs amounts are usually whole numbers, no need
    to always show '.00'."""
    value = float(value)
    return f"{value:.0f}" if value == int(value) else f"{value:.2f}"


def format_search_menu(result: dict) -> str:
    status = result["status"]
    if status == "exact":
        item = result["item"]
        sold_out = " (SOLD OUT)" if not item["is_available"] else ""
        return f"Exact match: #{item['id']} {item['name']} - Rs {_money(item['price'])}{sold_out}"

    suggestions = result["suggestions"]
    if not suggestions:
        return "No matching item found."

    listed = "; ".join(f"#{s['id']} {s['name']} (Rs {_money(s['price'])})" for s in suggestions)
    prefix = "Not an exact match." if status == "near" else "No match found."
    return f"{prefix} Closest options: {listed}"


def format_search_menu_batch(queries_and_results: list[tuple[str, dict]]) -> str:
    """queries_and_results: [(the query text, its search_menu result dict), ...] - one
    entry per item the caller asked about, checked in a single tool call instead of one
    round trip per item (each round trip is a full agent-tool-agent loop, i.e. a second
    LLM call, so N separate searches cost N times the tokens for what should be one)."""
    lines = [f'"{query}" -> {format_search_menu(result)}' for query, result in queries_and_results]
    return "\n".join(lines)


def format_check_availability(result: dict) -> str:
    if not result["available"]:
        return "No tables available for that date, time, and party size."
    tables = "; ".join(f"{t['name']} ({t['seats']} seats)" for t in result["tables"])
    return f"Available: {tables}"


def format_hold_slot(result: dict) -> str:
    if not result["available"]:
        return "No table available for that date, time, and party size."
    return (
        f"Held {result['table_name']}, reservation #{result['reservation_id']} "
        f"(expires {result['hold_expires_at']} if not confirmed)."
    )


def format_confirm_reservation(result: dict) -> str:
    return f"Reservation #{result['reservation_id']} confirmed."


def format_cancel_reservation(result: dict) -> str:
    return f"Reservation #{result['reservation_id']} cancelled."


def format_lookup_reservation(result: dict) -> str:
    reservations = result["reservations"]
    if not reservations:
        return "No reservations found."
    listed = "; ".join(
        f"#{r['id']} party of {r['party_size']} at {r['starts_at']} ({r['status']})"
        for r in reservations
    )
    return f"Found: {listed}"


def _order_totals_sentence(result: dict) -> str:
    return (
        f"order #{result['order_id']}: subtotal Rs {_money(result['subtotal'])}, "
        f"delivery Rs {_money(result['delivery_fee'])}, total Rs {_money(result['total'])}"
    )


def format_add_item_batch(lines: list[str], final_result: dict | None) -> str:
    """lines: one already-worded outcome per item attempted (see tools_binding.add_item -
    "#id x2: added (line #45)" or "#id: failed - <reason>"). final_result: the last
    successful add_item's totals dict, or None if every item in the batch failed."""
    body = "\n".join(lines)
    if final_result is None:
        return body
    return f"{body}\nNow {_order_totals_sentence(final_result)}."


def format_remove_item(result: dict) -> str:
    return f"Removed. Now {_order_totals_sentence(result)}."


def format_set_item_quantity(result: dict) -> str:
    return f"Updated. Now {_order_totals_sentence(result)}."


def format_cancel_order(result: dict) -> str:
    return f"Order #{result['order_id']} cancelled."


def format_set_delivery_address(result: dict) -> str:
    return f"Delivery address set for order #{result['order_id']}."


def format_get_order_summary(result: dict) -> str:
    if not result["items"]:
        items_str = "no items yet"
    else:
        lines = []
        for i in result["items"]:
            mods = f" ({', '.join(i['modifiers'])})" if i["modifiers"] else ""
            lines.append(
                f"line #{i['order_item_id']}: {i['quantity']}x {i['name']}{mods} "
                f"= Rs {_money(i['line_total'])}"
            )
        items_str = "; ".join(lines)
    address = "set" if result["address_id"] else "not set"
    return (
        f"Order #{result['order_id']} ({result['status']}): {items_str} | "
        f"subtotal Rs {_money(result['subtotal'])}, delivery Rs {_money(result['delivery_fee'])}, "
        f"total Rs {_money(result['total'])}, address {address}"
    )


def format_confirm_order(result: dict) -> str:
    return f"Order #{result['order_id']} confirmed. Total Rs {_money(result['total'])}."


def format_get_business_info(result: dict) -> str:
    return (
        f"{result['name']}, {result['address']}. Open {result['open_time']}-{result['close_time']} "
        f"({result['timezone']}), last order {result['last_order_time']}, last reservation "
        f"{result['last_reservation_start']}. Party size up to {result['max_party_size']}, "
        f"bookable up to {result['max_days_ahead']} days ahead, reservations last "
        f"{result['reservation_duration_minutes']} min. Delivery within {result['delivery_radius_km']}km, "
        f"{result['payment_mode'].replace('_', ' ')}, minimum Rs {_money(result['min_order_value'])}, "
        f"free above Rs {_money(result['free_delivery_above'])}, ETA {result['delivery_eta_minutes']} min."
    )
