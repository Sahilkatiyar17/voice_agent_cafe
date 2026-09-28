"""
Tests the agent's plumbing - SessionRef wiring, error surfacing, call-sheet rendering,
and how the model call is retried or fails - NOT full conversations. LLM output isn't deterministic and real calls cost tokens, so
conversation-level correctness is checked by hand via docs/phase3_test_conversations.md
and `python -m backend.agent.cli`, not asserted here.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from groq import BadRequestError
from langchain_core.messages import AIMessage
from sqlalchemy import select

from backend.agent.graph import LLM_FALLBACK_REPLY, MAX_LLM_ATTEMPTS, _invoke_llm
from backend.agent.prompts import build_system_prompt
from backend.agent.session import SessionRef, render_call_sheet
from backend.agent.tools_binding import make_tools
from backend.config import settings
from backend.tools.clock import get_today
from backend.tools.menu_cache import menu_cache
from database.connection import async_session
from database.models import MenuItem
from exception import CafeException
from tests.conftest import TEST_CALL_PREFIX, TEST_PHONE_PREFIX

pytestmark = pytest.mark.asyncio


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


async def _get_by_name(model, name: str):
    async with async_session() as session:
        return (await session.execute(select(model).where(model.name == name))).scalar_one()


async def test_add_item_tool_populates_session_order_id():
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT1")
    tools = make_tools(session)
    naan = await _get_by_name(MenuItem, "Butter Naan")

    assert session.order_id is None
    result = await _tool(tools, "add_item").ainvoke({"items": [{"menu_item_id": naan.id, "quantity": 2}]})

    # add_item now returns a short sentence, not the raw dict (see agent/formatting.py) -
    # session.order_id is the reliable way to check the write actually happened
    assert session.order_id is not None
    assert f"order #{session.order_id}" in result
    assert "120" in result  # 60 * 2


async def test_hold_slot_tool_populates_session_reservation_id():
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT2")
    tools = make_tools(session)
    slot_date = (date.today() + timedelta(days=6)).isoformat()

    assert session.reservation_id is None
    result = await _tool(tools, "hold_slot").ainvoke(
        {
            "date": slot_date,
            "time": "18:00",
            "party_size": 2,
            "customer_name": "Agent Test",
            "phone": f"{TEST_PHONE_PREFIX}5001",
        }
    )

    # hold_slot now returns a sentence, not the raw dict - session.reservation_id is the
    # reliable check that a hold actually happened
    assert session.reservation_id is not None
    assert f"reservation #{session.reservation_id}" in result


async def test_search_menu_tool_checks_a_whole_list_in_one_call():
    """search_menu takes a list so several items named in one sentence cost one tool call
    (one agent-tool-agent round trip) instead of one call per item."""
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT7")
    tools = make_tools(session)

    result = await _tool(tools, "search_menu").ainvoke(
        {"queries": ["butter naan", "matar paneer", "burger"]}
    )

    assert '"butter naan" ->' in result and "Exact match" in result
    assert '"matar paneer" ->' in result and "Palak Paneer" in result  # docs/spec.md's test hook
    assert '"burger" ->' in result  # the ambiguous alias, both options should be listed


async def test_add_item_tool_adds_a_whole_list_in_one_call():
    """Same reasoning as search_menu's batching - several items named in one sentence
    should cost one tool call, not one per item."""
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT8")
    tools = make_tools(session)
    naan = await _get_by_name(MenuItem, "Butter Naan")
    biryani = await _get_by_name(MenuItem, "Chicken Biryani")

    result = await _tool(tools, "add_item").ainvoke(
        {"items": [{"menu_item_id": naan.id, "quantity": 2}, {"menu_item_id": biryani.id, "quantity": 1}]}
    )

    assert session.order_id is not None
    assert f"#{naan.id} x2: added" in result
    assert f"#{biryani.id} x1: added" in result
    assert "470" in result  # 60*2 + 350 = 470 subtotal


async def test_add_item_batch_continues_past_a_failed_item():
    """One sold-out item in the batch must not block the others from being added."""
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT9")
    tools = make_tools(session)
    naan = await _get_by_name(MenuItem, "Butter Naan")

    result = await _tool(tools, "add_item").ainvoke(
        {"items": [{"menu_item_id": naan.id, "quantity": 1}, {"menu_item_id": 999999, "quantity": 1}]}
    )

    assert session.order_id is not None  # the naan still went through
    assert f"#{naan.id} x1: added" in result
    assert "#999999: failed" in result


async def test_wrapped_tool_raises_value_error_on_invalid_state():
    """No order exists yet for this session - remove_item must refuse cleanly (ValueError),
    which is what lets ToolNode turn it into an error message the LLM can react to,
    instead of an unhandled crash."""
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT3")
    tools = make_tools(session)

    with pytest.raises(ValueError):
        await _tool(tools, "remove_item").ainvoke({"order_item_id": 1})


async def test_render_call_sheet_reflects_live_order_state():
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT4")
    tools = make_tools(session)
    butter_chicken = await _get_by_name(MenuItem, "Butter Chicken")

    await _tool(tools, "add_item").ainvoke({"items": [{"menu_item_id": butter_chicken.id, "quantity": 1}]})

    sheet = await render_call_sheet(session)
    assert "Butter Chicken" in sheet
    assert "380" in sheet  # the item's price (docs/spec.md), which is also the subtotal here


async def test_cancel_order_tool_requires_an_existing_order():
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT5")
    tools = make_tools(session)

    with pytest.raises(ValueError):
        await _tool(tools, "cancel_order").ainvoke({})


# ---------------------------------------------------------------------------
# Error handling around the model call (graph._invoke_llm). None of these call Groq:
# they use a fake model that returns or raises whatever the test tells it to.
# ---------------------------------------------------------------------------

class _FakeLLM:
    """Stands in for the bound Groq model. `outcomes` is consumed one per call; an
    Exception in the list is raised, anything else is returned."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _bad_request(message: str) -> BadRequestError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return BadRequestError(message, response=httpx.Response(400, request=request), body=None)


# the shape of the real error you hit: the model called a tool with a null argument
_TOOL_USE_FAILED = "Error code: 400 - {'error': {'code': 'tool_use_failed'}}"


async def test_invalid_tool_call_is_retried_and_the_retry_succeeds():
    llm = _FakeLLM([_bad_request(_TOOL_USE_FAILED), AIMessage(content="How many people?")])

    reply = await _invoke_llm(llm, [], "PYTEST_LLM1")

    assert reply.content == "How many people?"
    assert llm.calls == 2


async def test_invalid_tool_call_twice_gives_the_fallback_reply_not_a_crash():
    llm = _FakeLLM([_bad_request(_TOOL_USE_FAILED)] * MAX_LLM_ATTEMPTS)

    reply = await _invoke_llm(llm, [], "PYTEST_LLM2")

    assert reply.content == LLM_FALLBACK_REPLY
    assert llm.calls == MAX_LLM_ATTEMPTS


async def test_a_different_400_is_not_retried_and_crashes_loudly():
    """Only tool_use_failed is the model's fault. Any other 400 is our bug and must not be
    hidden behind a polite fallback reply."""
    llm = _FakeLLM([_bad_request("Error code: 400 - prompt is too long")])

    with pytest.raises(CafeException):
        await _invoke_llm(llm, [], "PYTEST_LLM3")
    assert llm.calls == 1


async def test_an_unexpected_error_becomes_cafe_exception():
    llm = _FakeLLM([RuntimeError("boom")])

    with pytest.raises(CafeException):
        await _invoke_llm(llm, [], "PYTEST_LLM4")
    assert llm.calls == 1


async def test_render_call_sheet_failure_becomes_cafe_exception():
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_AGENT6", order_id=999_999_999)  # no such order

    with pytest.raises(CafeException):
        await render_call_sheet(session)


async def test_system_prompt_refuses_to_build_with_an_unloaded_menu(monkeypatch):
    monkeypatch.setattr(menu_cache, "items", [])  # is_loaded() is bool(items)

    with pytest.raises(RuntimeError):
        build_system_prompt(date(2026, 9, 26))


# ---------------------------------------------------------------------------
# The current date: get_today, SessionRef.today, and the calendar in the prompt.
# ---------------------------------------------------------------------------

async def test_get_today_uses_the_cafe_timezone_not_utc():
    utc = ZoneInfo("UTC")
    # 20:00 UTC on the 26th is 01:30 on the 27th in India - the cafe's date has moved on
    assert get_today(datetime(2026, 9, 26, 20, 0, tzinfo=utc)) == date(2026, 9, 27)
    # 10:00 UTC is 15:30 in India - still the same day
    assert get_today(datetime(2026, 9, 26, 10, 0, tzinfo=utc)) == date(2026, 9, 26)


async def test_session_ref_loads_today_when_it_is_created():
    session = SessionRef(call_id=f"{TEST_CALL_PREFIX}_DATE1")

    assert isinstance(session.today, date)
    assert session.today == get_today()  # only differs if the cafe's clock ticks past midnight mid-test


async def test_system_prompt_lists_today_and_the_next_14_days():
    prompt = build_system_prompt(date(2026, 9, 26))  # a Saturday

    assert "Saturday 2026-09-26 (today)" in prompt
    assert "Sunday 2026-09-27 (tomorrow)" in prompt
    assert "2026-10-10" in prompt  # 14 days ahead - the booking window (MAX_DAYS_AHEAD)
    assert "2026-10-11" not in prompt  # day 15 is outside it


@pytest.mark.skipif(not settings.groq_api_key, reason="needs GROQ_API_KEY in .env")
async def test_graph_smoke_real_llm_call():
    """One real end-to-end turn through Groq - kept singular and structural-only (not
    asserting on wording) since it's slow and spends real tokens. Confirms build_graph
    wires together without error and that history round-trips via the checkpointer."""
    from langchain_core.messages import HumanMessage

    from backend.agent.graph import build_graph
    from backend.tools.menu_cache import menu_cache

    if not menu_cache.is_loaded():
        await menu_cache.load()

    call_id = f"{TEST_CALL_PREFIX}_AGENT_SMOKE"
    graph, _session = build_graph(call_id)
    config = {"configurable": {"thread_id": call_id}}

    result1 = await graph.ainvoke({"messages": [HumanMessage("What are your hours?")]}, config=config)
    assert result1["messages"][-1].content.strip()

    # a second turn on the same thread_id should see the first turn's history
    result2 = await graph.ainvoke({"messages": [HumanMessage("And what about delivery?")]}, config=config)
    assert result2["messages"][-1].content.strip()
    assert len(result2["messages"]) > len(result1["messages"])
