"""search_menu: exact / near / not_found, against the spec's test hooks (docs/spec.md)."""

from backend.tools.search_menu import search_menu


def test_exact_match_on_alias():
    result = search_menu("naan")
    assert result["status"] == "exact"
    assert result["item"]["name"] == "Butter Naan"


def test_ambiguous_alias_is_near_with_both_options():
    """'burger' is an alias shared by two items - not a confident single match."""
    result = search_menu("burger")
    assert result["status"] == "near"
    names = {s["name"] for s in result["suggestions"]}
    assert names == {"Grilled Chicken Burger", "Veggie Burger"}


def test_fuzzy_miss_suggests_the_nearest_item():
    """docs/spec.md: 'matar paneer' -> not found, nearest: Palak Paneer."""
    result = search_menu("matar paneer")
    names = [s["name"] for s in result["suggestions"]]
    assert result["status"] in ("near", "not_found")
    assert "Palak Paneer" in names


def test_gibberish_is_not_found_with_no_suggestions():
    result = search_menu("xyzzyxyz totally not food")
    assert result["status"] == "not_found"
    assert result["suggestions"] == []


def test_sold_out_item_still_matches_but_flags_unavailable(monkeypatch):
    """search_menu must never hide a sold-out item - is_available rides along on the result,
    the item still 'exists' on the menu (see backend/tools/search_menu.py docstring)."""
    from backend.tools.menu_cache import menu_cache

    naan = next(i for i in menu_cache.items if i["name"] == "Butter Naan")
    original = naan["is_available"]
    naan["is_available"] = False
    try:
        result = search_menu("naan")
        assert result["status"] == "exact"
        assert result["item"]["is_available"] is False
    finally:
        naan["is_available"] = original
