"""The graph's checkpointed state: just the message history. Order/reservation ids
deliberately live on SessionRef (session.py), not here - one graph instance is built per
call (see graph.build_graph), so nothing about a call's identifiers needs to survive a
process restart in this phase. That assumption changes once Phase 5/6 make calls span
processes and need a durable checkpointer instead of MemorySaver."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
