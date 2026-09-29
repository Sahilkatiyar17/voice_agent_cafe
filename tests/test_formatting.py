"""
Tests backend/agent/formatting.py: every function is pure (no DB, no LLM, no async), so
these run instantly and cost nothing. Each test feeds a realistic result dict (the exact
shape the matching Phase 2 tool actually returns - see backend/tools/*.py) and checks the
sentence keeps whatever a later tool call would need (mainly: ids).
"""

import pytest

from backend.agent import formatting as fmt

pytestmark = pytest.mark.no_db  # pure logic - runs without Postgres


def test_search_menu_exact_keeps_the_id_for_a_later_add_item_call():
    result = {
        "status": "exact",
        "item": {"id": 5, "name": "Chicken Biryani", "category": "indian", "is_veg": False,
                  "price": 350.0, "is_available": True},
        "suggestions": [],
    }
    text = fmt.format_search_menu(result)
    assert "#5" in text
    assert "Chicken Biryani" in text
    assert "350" in text


def test_search_menu_exact_flags_sold_out():
    result = {
        "status": "exact",
        "item": {"id": 4, "name": "Butter Chicken", "category": "indian", "is_veg": False,
                  "price": 380.0, "is_available": False},
        "suggestions": [],
    }
    assert "SOLD OUT" in fmt.format_search_menu(result)


def test_search_menu_near_keeps_ids_of_all_suggestions():
    result = {
        "status": "near",
        "item": None,
        "suggestions": [
            {"id": 25, "name": "Grilled Chicken Burger", "category": "continental",
             "is_veg": False, "price": 350.0, "is_available": True},
            {"id": 26, "name": "Veggie Burger", "category": "continental",
             "is_veg": True, "price": 290.0, "is_available": True},
        ],
    }
    text = fmt.format_search_menu(result)
    assert "#25" in text and "#26" in text


def test_search_menu_not_found_with_no_suggestions():
    result = {"status": "not_found", "item": None, "suggestions": []}
    assert fmt.format_search_menu(result) == "No matching item found."


def test_search_menu_batch_labels_each_result_by_its_own_query():
    results = [
        ("chicken biryani", {
            "status": "exact",
            "item": {"id": 5, "name": "Chicken Biryani", "category": "indian", "is_veg": False,
                      "price": 350.0, "is_available": True},
            "suggestions": [],
        }),
        ("matar paneer", {
            "status": "not_found",
            "item": None,
            "suggestions": [
                {"id": 2, "name": "Palak Paneer", "category": "indian", "is_veg": True,
                 "price": 300.0, "is_available": True},
            ],
        }),
    ]
    text = fmt.format_search_menu_batch(results)

    assert '"chicken biryani" ->' in text
    assert '"matar paneer" ->' in text
    assert "#5" in text  # the exact match's id is still there
    assert "#2" in text  # so is the suggestion's id, for the second query
    assert text.count("\n") == 1  # one line per query


def test_check_availability_lists_tables_when_available():
    result = {"available": True, "tables": [{"id": 1, "name": "T1", "seats": 2}]}
    assert "T1" in fmt.format_check_availability(result)


def test_check_availability_says_none_free():
    result = {"available": False, "tables": []}
    assert "No tables" in fmt.format_check_availability(result)


def test_hold_slot_keeps_the_reservation_id():
    result = {"available": True, "reservation_id": 42, "table_name": "T3", "hold_expires_at": "2026-01-01T00:00:00"}
    assert "#42" in fmt.format_hold_slot(result)


def test_hold_slot_unavailable():
    result = {"available": False, "reservation_id": None}
    assert "No table available" in fmt.format_hold_slot(result)


def test_confirm_and_cancel_reservation_keep_the_id():
    assert "#7" in fmt.format_confirm_reservation({"confirmed": True, "reservation_id": 7})
    assert "#7" in fmt.format_cancel_reservation({"cancelled": True, "reservation_id": 7})


def test_lookup_reservation_empty():
    assert fmt.format_lookup_reservation({"reservations": []}) == "No reservations found."


def test_lookup_reservation_shows_status_of_each():
    result = {
        "reservations": [
            {"id": 1, "table_id": 3, "customer_name": "A", "party_size": 2,
             "starts_at": "2026-10-01T19:00:00", "status": "cancelled"},
        ]
    }
    text = fmt.format_lookup_reservation(result)
    assert "#1" in text and "cancelled" in text


def test_add_item_batch_keeps_order_id_and_line_ids():
    final_result = {"order_item_id": 46, "order_id": 69, "subtotal": 440.0, "delivery_fee": 40.0, "total": 480.0}
    lines = [
        "#5 x1: added (line #45)",
        "#7 x2: added (line #46)",
    ]
    text = fmt.format_add_item_batch(lines, final_result)
    assert "#45" in text and "#46" in text
    assert "order #69" in text
    assert "480" in text


def test_add_item_batch_all_failed_has_no_totals_line():
    lines = ["#99: failed - No such menu item."]
    text = fmt.format_add_item_batch(lines, None)
    assert text == "#99: failed - No such menu item."


def test_remove_item_and_set_quantity_keep_order_id():
    result = {"order_id": 69, "subtotal": 60.0, "delivery_fee": 40.0, "total": 100.0}
    assert "order #69" in fmt.format_remove_item(result)
    assert "order #69" in fmt.format_set_item_quantity(result)


def test_cancel_order_and_set_delivery_address_keep_order_id():
    assert "#69" in fmt.format_cancel_order({"cancelled": True, "order_id": 69})
    assert "#69" in fmt.format_set_delivery_address({"order_id": 69, "address_id": 12})


def test_get_order_summary_keeps_line_ids_and_modifiers():
    result = {
        "order_id": 69,
        "status": "draft",
        "items": [
            {"order_item_id": 1, "name": "Butter Chicken", "quantity": 1, "unit_price": 380.0,
             "modifiers": ["hot"], "line_total": 380.0},
        ],
        "subtotal": 380.0,
        "delivery_fee": 40.0,
        "total": 420.0,
        "address_id": None,
    }
    text = fmt.format_get_order_summary(result)
    assert "line #1" in text
    assert "hot" in text
    assert "address not set" in text


def test_get_order_summary_empty_order():
    result = {
        "order_id": 5, "status": "draft", "items": [], "subtotal": 0.0,
        "delivery_fee": 0.0, "total": 0.0, "address_id": None,
    }
    assert "no items yet" in fmt.format_get_order_summary(result)


def test_confirm_order_keeps_id_and_total():
    text = fmt.format_confirm_order({"confirmed": True, "order_id": 69, "total": 420.0})
    assert "#69" in text and "420" in text


def test_get_business_info_is_one_compact_line():
    result = {
        "name": "Saffron & Seoul", "address": "12th Main Road, Indiranagar", "timezone": "Asia/Kolkata",
        "open_time": "11:00", "close_time": "23:00", "last_order_time": "22:30",
        "last_reservation_start": "21:30", "reservation_duration_minutes": 90, "max_party_size": 6,
        "max_days_ahead": 14, "delivery_radius_km": 5, "min_order_value": 250,
        "free_delivery_above": 700, "delivery_eta_minutes": 40, "payment_mode": "cash_on_delivery",
    }
    text = fmt.format_get_business_info(result)
    assert "\n" not in text
    assert "Saffron & Seoul" in text
    assert "cash on delivery" in text


def test_money_drops_trailing_zero_but_keeps_real_cents():
    assert fmt._money(450.0) == "450"
    assert fmt._money(449.5) == "449.50"
