from fastapi import APIRouter, Query

from backend.api.errors import handle_tool_errors
from backend.tools.menu_cache import menu_cache
from backend.tools.search_menu import search_menu

router = APIRouter(prefix="/menu", tags=["menu"])


@router.get("/search")
@handle_tool_errors
async def search(query: str = Query(..., description="e.g. 'burger', 'matar paneer'")):
    return search_menu(query)


@router.post("/refresh")
@handle_tool_errors
async def refresh():
    """Reloads the in-memory menu cache from the database. Call this after an admin edits
    a menu item (Phase 5's menu manager will call it automatically); without it, changes
    made directly in the DB aren't picked up until the API process restarts."""
    await menu_cache.load()
    return {"reloaded": True, "items": len(menu_cache.items)}
