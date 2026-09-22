"""
search_menu: the ONLY way the agent finds out whether an item is on the menu.

The LLM never decides "is this on the menu" itself - it calls this tool and gets back
one of three answers (see restaurant_voice_agent_plan.md, Phase 2):
  - "exact"     - one item matches the name or an alias exactly
  - "near"      - no single confident match; here are close candidates to offer the caller
  - "not_found" - nothing close enough; "suggestions" may still be non-empty (see below)

Availability (is_available) is reported on the item, never filtered out here - a sold-out
item still "exists" on the menu, it just can't be ordered right now. confirm_order is what
must re-check availability before writing.
"""

from rapidfuzz import fuzz

from backend.tools.menu_cache import menu_cache, public_item

# Tuned by hand against the spec's test hooks (docs/spec.md "Test hooks"), not measured yet -
# revisit once you've run real scripted conversations (Phase 3) against this.
NEAR_THRESHOLD = 75  # score >= this: confident enough to call it a "near" match
MIN_THRESHOLD = 55  # score below this: too unrelated to even suggest
MAX_SUGGESTIONS = 3


def _clean(text: str) -> str:
    return text.strip().lower()


def _candidates(item: dict) -> list[str]:
    return [item["name"], *item["aliases"]]


def search_menu(query: str) -> dict:
    """
    Returns:
        {
            "status": "exact" | "near" | "not_found",
            "item": <public item dict> | None,       # set only when status == "exact"
            "suggestions": [<public item dict>, ...], # set for "near", and often for "not_found"
        }
    """
    if not menu_cache.is_loaded():
        raise RuntimeError("menu_cache is empty - call `await menu_cache.load()` at startup")

    query_clean = _clean(query)
    if not query_clean:
        return {"status": "not_found", "item": None, "suggestions": []}

    # ---- 1. exact match on name or alias, case-insensitive ----
    exact_item_ids = {
        item["id"]
        for item in menu_cache.items
        if any(_clean(c) == query_clean for c in _candidates(item))
    }

    if len(exact_item_ids) == 1:
        item = menu_cache.by_id[next(iter(exact_item_ids))]
        return {"status": "exact", "item": public_item(item), "suggestions": []}

    if len(exact_item_ids) > 1:
        # Same name/alias shared by more than one item (e.g. "burger" is an alias for both
        # the chicken and veggie burger) - not a confident single match, ask which one.
        items = [public_item(menu_cache.by_id[i]) for i in exact_item_ids]
        return {"status": "near", "item": None, "suggestions": items}

    # ---- 2. fuzzy fallback: best score per item across its name + aliases ----
    scored: list[tuple[dict, float]] = []
    for item in menu_cache.items:
        best_score = max(fuzz.WRatio(query_clean, _clean(c)) for c in _candidates(item))
        scored.append((item, best_score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    close_enough = [(item, score) for item, score in scored if score >= MIN_THRESHOLD]

    if not close_enough:
        return {"status": "not_found", "item": None, "suggestions": []}

    top = close_enough[:MAX_SUGGESTIONS]
    suggestions = [public_item(item) for item, _score in top]
    status = "near" if top[0][1] >= NEAR_THRESHOLD else "not_found"
    return {"status": status, "item": None, "suggestions": suggestions}
