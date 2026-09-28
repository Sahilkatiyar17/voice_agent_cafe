"""
Runs the scripted conversations from docs/phase3_test_conversations.md against the real
agent (real Groq calls, real database) and saves a full transcript per scenario - tool
calls, their results, and every reply - for you to check against that document's "Expect"
notes.

This is NOT a pass/fail test suite. LLM phrasing isn't deterministic, so there is no
assertion this script could make that would mean anything - it runs the conversation and
gets out of the way. tests/test_agent_graph.py is the actual automated suite (tool wiring,
error handling, formatting); this is for your own judgment, same numbering as the checklist
so a transcript and a checklist line always match up.

Usage (from the project root, venv active):
    python -m evals.run_scenarios --list                  # show every scenario id/title
    python -m evals.run_scenarios --only A                 # just group A (menu search)
    python -m evals.run_scenarios --scenario B7             # just one scenario
    python -m evals.run_scenarios --only B --delay 12       # slower pacing if you hit 429s
    python -m evals.run_scenarios --only C --slow           # include C18/C21 (DB setup, more tokens)
    python -m evals.run_scenarios --only C --slow --hold-expiry   # also C22 (~6 min real wait)

Output: evals/transcripts/<run timestamp>/<scenario id>.txt, plus a one-line result per
scenario on the console (COMPLETED or CRASHED - never PASSED, see above).

Each scenario's own conversation is cleaned up afterward (orders/reservations tagged with
its call_id are deleted) so repeated runs don't clutter the dev database the way manual
CLI sessions do (see cli.py's own docstring on that same gap).
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import text

from sqlalchemy import select, update

from backend.agent.graph import build_graph
from backend.tools.clock import get_today
from backend.tools.menu_cache import menu_cache
from backend.tools.reservations import hold_slot
from database.connection import async_session, engine
from database.models import MenuItem
from logger import logging

DEFAULT_DELAY_SECONDS = 8  # pause between turns - stays under Groq's free-tier rate limit


@dataclass
class Scenario:
    id: str
    title: str
    group: str
    turns: list[str]
    setup: Callable[[], "asyncio.Future"] | None = None  # runs before the conversation
    teardown: Callable[[], "asyncio.Future"] | None = None  # always runs after, even on crash
    slow: bool = False  # needs --slow (DB setup, or a real multi-minute wait)
    hold_expiry: bool = False  # needs --hold-expiry too (waits past HOLD_EXPIRY_MINUTES)


async def _cleanup(call_id: str) -> None:
    """Deletes anything this scenario's conversation created, keyed by call_id - same
    approach as tests/conftest.py, so eval runs don't leave debris like manual CLI
    sessions do."""
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM reservations WHERE call_id = :c"), {"c": call_id})
        await conn.execute(
            text(
                "DELETE FROM order_item_modifiers WHERE order_item_id IN "
                "(SELECT id FROM order_items WHERE order_id IN "
                "(SELECT id FROM orders WHERE call_id = :c))"
            ),
            {"c": call_id},
        )
        await conn.execute(
            text("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE call_id = :c)"),
            {"c": call_id},
        )
        await conn.execute(text("DELETE FROM orders WHERE call_id = :c"), {"c": call_id})


async def _block_out_slot(date_str: str, time_str: str, call_id_prefix: str) -> None:
    """Holds every table for one slot, for scenarios that need 'nothing available' to be
    true (#18, #21). Uses party_size=2 repeatedly since every table seats at least 2."""
    for i in range(10):
        await hold_slot(date_str, time_str, 2, f"Eval Blocker {i}", f"9999{i:06d}", call_id=f"{call_id_prefix}{i}")


async def _set_item_available(name: str, available: bool) -> None:
    """Flips a menu item's is_available and reloads menu_cache - no CLI restart needed
    (docs/phase3_test_conversations.md's manual instructions assumed a separate process;
    this script controls its own lifecycle, so it can just reload the cache directly)."""
    async with async_session() as session:
        item = (await session.execute(select(MenuItem).where(MenuItem.name == name))).scalar_one()
        await session.execute(update(MenuItem).where(MenuItem.id == item.id).values(is_available=available))
        await session.commit()
    await menu_cache.load()


def _build_scenarios() -> list[Scenario]:
    today = get_today()

    def d(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    scenarios: list[Scenario] = [
        # ---------------- A. Menu search ----------------
        Scenario("A1", "Not on menu, suggestion", "A", ["do you have matar paneer"]),
        Scenario("A2", "Ambiguous alias", "A", ["I'd like a burger"]),
        Scenario("A3", "Category listing", "A", ["what continental items do you have"]),
        Scenario("A4", "Exact price check", "A", ["how much is the butter naan"]),
        Scenario(
            "A5", "Sold out mid-order", "A",
            ["I'll have the butter chicken"],
            setup=lambda: _set_item_available("Butter Chicken", False),
            teardown=lambda: _set_item_available("Butter Chicken", True),
            slow=True,  # touches real menu data - opt in with --slow
        ),

        # ---------------- B. Ordering ----------------
        Scenario("B6", "Add single item", "B", ["I'd like a chicken biryani", "just one"]),
        Scenario("B7", "Add several items", "B", ["I'd like a chicken biryani and two butter naan"]),
        Scenario(
            "B8", "Add then remove (burger)", "B",
            ["I'll have a chicken burger", "the chicken one, just one", "actually remove the burger"],
        ),
        Scenario("B9", "Change quantity", "B", ["I'd like one butter naan", "make that two"]),
        Scenario(
            "B10", "Ambiguous item mid-order", "B",
            ["I'd like a chicken biryani", "add a burger too"],
        ),
        Scenario("B11", "Item with a modifier", "B", ["I'll have the butter chicken, extra hot"]),
        Scenario(
            "B12", "Full happy path", "B",
            [
                "I'd like two butter naan",
                "my phone is 9998880001, address 12 MG Road, pincode 560038",
                "yes please confirm",
            ],
        ),
        Scenario(
            "B13", "Address outside delivery area", "B",
            ["I'd like a chicken biryani", "my phone is 9998880002, address 5 Fake Street, pincode 999999"],
        ),
        Scenario(
            "B14", "Below minimum order", "B",
            ["I'd like one masala chai", "my phone is 9998880003, address 1 Test Rd, pincode 560038, please confirm"],
        ),

        # ---------------- C. Reservations ----------------
        Scenario(
            "C15", "Full booking happy path", "C",
            [f"I'd like a table for 2 on {d(2)} at 19:00", "Eval Fifteen, phone 9998880015", "yes confirm it"],
        ),
        Scenario("C16", "Party size over the limit", "C", [f"table for 10 on {d(2)} at 19:00"]),
        Scenario("C17", "Out of hours / past date", "C", ["table for 2 yesterday at 2am"]),
        Scenario(
            "C18", "No tables available", "C",
            [f"table for 2 on {d(3)} at 19:00"],
            setup=lambda: _block_out_slot(d(3), "19:00", "EVALSETUP-C18-"),
            slow=True,
        ),
        Scenario(
            "C19", "Lookup by phone", "C",
            [
                f"table for 2 on {d(4)} at 19:00", "Eval Nineteen, phone 9998880019", "yes confirm it",
                "what's the status of my reservation, phone 9998880019",
            ],
        ),
        Scenario(
            "C20", "Cancel a reservation", "C",
            [
                f"table for 2 on {d(5)} at 19:00", "Eval Twenty, phone 9998880020", "yes confirm it",
                "actually cancel that",
            ],
        ),
        Scenario(
            "C21", "Double-booked slot", "C",
            [f"table for 2 on {d(3)} at 19:00"],  # reuses C18's blocked slot - run C18's setup first
            setup=lambda: _block_out_slot(d(3), "19:00", "EVALSETUP-C21-"),
            slow=True,
        ),
        Scenario(
            "C22", "Hold expiring before confirming", "C",
            [f"table for 2 on {d(6)} at 19:00", "Eval Twentytwo, phone 9998880022"],
            slow=True,
            hold_expiry=True,
        ),

        # ---------------- D. Mixed and edge cases ----------------
        Scenario(
            "D23", "Reservation and order in one call", "D",
            [f"book a table for 2 on {d(7)} at 20:00, and also order some naan for delivery tomorrow"],
        ),
        Scenario(
            "D24", "Changing your mind mid-flow", "D",
            [f"table for 2 on {d(8)} at 19:00", "actually make that four"],
        ),
        Scenario(
            "D25", "Interruption with an info question", "D",
            ["I'd like a chicken biryani", "what time do you close?", "ok continue with my order"],
        ),
        Scenario(
            "D26", "Forced tool error (double confirm)", "D",
            [
                "I'd like two butter naan", "my phone is 9998880026, address 9 Test Ave, pincode 560038",
                "yes confirm it", "please confirm it again",
            ],
        ),
        Scenario("D27", "Out-of-scope request", "D", ["can I get a refund on my last order"]),
        Scenario(
            "D28", "Terse utterances", "D",
            ["chicken biryani", "1", "9998880028", "9 short st, 560038", "yes"],
        ),
        Scenario("D29", "Price without ordering", "D", ["how much is the chicken biryani"]),
        Scenario(
            "D30", "Cancel whole order", "D",
            ["I'd like a chicken biryani and a butter naan", "never mind, forget the whole order"],
        ),
    ]
    return scenarios


async def _run_one(scenario: Scenario, out_dir: Path, delay: int) -> bool:
    """Returns True if the conversation completed without an unhandled exception."""
    call_id = f"EVAL-{scenario.id}-{scenario.title[:10].replace(' ', '')}"
    lines = [f"SCENARIO {scenario.id}: {scenario.title}", "=" * 70]
    ok = True

    try:
        if scenario.setup:
            lines.append("(running setup...)")
            await scenario.setup()

        graph, _session = build_graph(call_id)
        config = {"configurable": {"thread_id": call_id}}

        for turn in scenario.turns:
            lines.append(f"\nYou: {turn}")
            await asyncio.sleep(delay)
            result = await graph.ainvoke({"messages": [HumanMessage(turn)]}, config=config)
            msgs = result["messages"]
            human_idx = max(i for i, m in enumerate(msgs) if isinstance(m, HumanMessage) and m.content == turn)
            for m in msgs[human_idx + 1:]:
                if isinstance(m, AIMessage) and m.tool_calls:
                    for tc in m.tool_calls:
                        lines.append(f"  [calls {tc['name']}({tc['args']})]")
                elif isinstance(m, ToolMessage):
                    status = getattr(m, "status", "?")
                    lines.append(f"  [{m.name} -> {status}] {str(m.content)[:300]}")
            lines.append(f"Agent: {msgs[-1].content or '(EMPTY - see docs/phase3_test_conversations.md notes)'}")

        if scenario.hold_expiry:
            wait_minutes = 6  # HOLD_EXPIRY_MINUTES (5) plus a margin
            lines.append(f"\n(waiting {wait_minutes} minutes for the hold to expire...)")
            await asyncio.sleep(wait_minutes * 60)
            confirm_turn = "yes, confirm it"
            lines.append(f"\nYou: {confirm_turn}")
            result = await graph.ainvoke({"messages": [HumanMessage(confirm_turn)]}, config=config)
            lines.append(f"Agent: {result['messages'][-1].content}")

    except Exception as e:
        ok = False
        lines.append(f"\n!!! CRASHED: {type(e).__name__}: {e}")
        logging.error("Scenario %s crashed: %s", scenario.id, e)
    finally:
        await _cleanup(call_id)
        if scenario.teardown:
            await scenario.teardown()

    (out_dir / f"{scenario.id}.txt").write_text("\n".join(lines), encoding="utf-8")
    return ok


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="list every scenario id/title and exit")
    parser.add_argument("--only", choices=["A", "B", "C", "D"], help="run only this group")
    parser.add_argument("--scenario", help="run only this one scenario id, e.g. B7")
    parser.add_argument("--delay", type=int, default=DEFAULT_DELAY_SECONDS, help="seconds between turns")
    parser.add_argument("--slow", action="store_true", help="include DB-setup scenarios (C18, C21)")
    parser.add_argument("--hold-expiry", action="store_true", help="also run C22 (~6 minute real wait)")
    args = parser.parse_args()

    scenarios = _build_scenarios()

    if args.list:
        for s in scenarios:
            flags = " ".join(f for f, on in (("slow", s.slow), ("hold-expiry", s.hold_expiry)) if on)
            print(f"{s.id:5} [{s.group}] {s.title}{'  (' + flags + ')' if flags else ''}")
        return

    if args.scenario:
        scenarios = [s for s in scenarios if s.id == args.scenario]
        if not scenarios:
            print(f"No such scenario: {args.scenario}")
            return
    elif args.only:
        scenarios = [s for s in scenarios if s.group == args.only]

    if not args.slow:
        scenarios = [s for s in scenarios if not s.slow]
    if not args.hold_expiry:
        scenarios = [s for s in scenarios if not s.hold_expiry]

    if not scenarios:
        print("Nothing to run - check --only/--scenario/--slow/--hold-expiry.")
        return

    await menu_cache.load()

    run_dir = Path(__file__).parent / "transcripts" / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(scenarios)} scenario(s), delay={args.delay}s. Transcripts -> {run_dir}\n")
    for scenario in scenarios:
        ok = await _run_one(scenario, run_dir, args.delay)
        print(f"{'COMPLETED' if ok else 'CRASHED  '}  {scenario.id}  {scenario.title}")

    print(f"\nDone. Read each transcript in {run_dir} against docs/phase3_test_conversations.md.")


if __name__ == "__main__":
    asyncio.run(main())
