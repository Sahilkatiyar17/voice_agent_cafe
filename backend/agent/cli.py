"""
A plain text REPL for manually running the Phase 3 agent - the primary way to work
through docs/phase3_test_conversations.md.

Run from the project root, venv active:
    python -m backend.agent.cli

Known gap: each run creates a new call_id like "CLI-<hex>" and nothing cleans up the
draft orders / expired holds it leaves in the dev database (unlike pytest's tests, whose
rows are tagged with a PYTEST/9991 prefix that tests/conftest.py deletes automatically).
Fine for manual testing; periodically wipe branch_id=1 draft orders and expired holds by
hand if the dev DB gets cluttered.
"""

import asyncio
import uuid

from langchain_core.messages import HumanMessage

from backend.agent.graph import build_graph
from backend.tools.menu_cache import menu_cache
from exception import CafeException
from logger import logging


async def main() -> None:
    await menu_cache.load()

    call_id = f"CLI-{uuid.uuid4().hex[:8]}"
    graph, _session = build_graph(call_id)
    config = {"configurable": {"thread_id": call_id}}
    logging.info("CLI session started, call_id=%s", call_id)

    print(f"Text agent ready (call_id={call_id}). Type 'quit' to exit.\n")
    while True:
        user_text = input("You: ").strip()
        if not user_text:
            continue
        if user_text.lower() in ("quit", "exit"):
            break

        try:
            result = await graph.ainvoke({"messages": [HumanMessage(content=user_text)]}, config=config)
        except CafeException:
            # CafeException has already logged the file and line. For a manual test session
            # it's more useful to keep going than to lose the whole conversation; the
            # failed turn's message may still be in the history, which is fine for testing.
            print("Agent: Something went wrong on my side - see the error logged above.\n")
            continue

        reply = result["messages"][-1].content
        print(f"Agent: {reply}\n")

    logging.info("CLI session ended, call_id=%s", call_id)


if __name__ == "__main__":
    asyncio.run(main())
