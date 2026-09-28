"""
Builds the LangGraph agent: two nodes, agent and tools, looping until the model has
nothing left to call.

    START -> agent --(tool_calls present?)--> tools -> agent -> ... -> END

Usage:
    graph, session = build_graph(call_id)
    result = await graph.ainvoke(
        {"messages": [HumanMessage("I'd like a table for two")]},
        config={"configurable": {"thread_id": call_id}},
    )
    reply = result["messages"][-1].content
"""

import sys

from groq import BadRequestError
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from backend.agent.llm import get_chat_model
from backend.agent.prompts import build_system_prompt
from backend.agent.session import SessionRef, render_call_sheet
from backend.agent.state import AgentState
from backend.agent.tools_binding import make_tools
from exception import CafeException
from logger import logging

# What the caller sees if the model fails twice in a row on the same turn.
LLM_FALLBACK_REPLY = "Sorry, I didn't quite catch that. Could you say that again?"
MAX_LLM_ATTEMPTS = 2  # the first try, plus one retry


def _domain_error_message(e: ValueError) -> str:
    """Passed as ToolNode's handle_tool_errors. ToolNode reads this function's own type
    annotation (ValueError, above) to decide WHICH exceptions to catch - see
    _infer_handled_types in langgraph's prebuilt/tool_node.py. Only ValueError (Phase 2's
    convention for an expected domain error - sold out, wrong pincode, no such
    reservation) gets turned into a message; anything else (a genuine bug, wrapped in
    CafeException by tools_binding._call) is deliberately left to propagate and crash
    loudly instead of being hidden from you as a polite-sounding error message.

    Without this, ToolNode's OWN default only catches its internal ToolInvocationError
    (bad arguments) and re-raises everything else - including our own ValueErrors -
    which is what crashed the whole CLI process the first time this was tried."""
    return str(e)


def _is_invalid_tool_call(e: BadRequestError) -> bool:
    """Groq checks the model's tool call against our tool schema BEFORE handing it back,
    and answers 400 with code 'tool_use_failed' if the model got it wrong - for example
    calling check_availability with party_size=null because it hadn't asked for a party
    size yet. That is the model misbehaving, not a bug in our code, so it's the one 400 we
    treat as retryable. Any other 400 (a malformed request, a prompt that's too long) is
    OUR problem and must not be hidden behind a polite reply."""
    return "tool_use_failed" in str(e)


async def _invoke_llm(llm, messages: list, call_id: str) -> AIMessage:
    """Calls the model. Only an invalid tool call from the model is retried (once); if that
    fails again the caller gets LLM_FALLBACK_REPLY instead of a crashed conversation. Every
    other failure is unexpected - it's wrapped in CafeException (which logs the file and
    line) and left to crash loudly, the same rule the tools follow."""
    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
        try:
            return await llm.ainvoke(messages)
        except BadRequestError as e:
            if not _is_invalid_tool_call(e):
                raise CafeException(e, sys) from e
            logging.warning(
                "[%s] model produced an invalid tool call (attempt %d of %d): %s",
                call_id, attempt, MAX_LLM_ATTEMPTS, e,
            )
        except Exception as e:
            raise CafeException(e, sys) from e

    logging.error("[%s] model failed %d times in a row - sending the fallback reply", call_id, MAX_LLM_ATTEMPTS)
    return AIMessage(content=LLM_FALLBACK_REPLY)


def build_graph(call_id: str):
    session = SessionRef(call_id=call_id)
    tools = make_tools(session)
    llm = get_chat_model().bind_tools(tools)

    async def agent_node(state: AgentState) -> dict:
        # Rebuilt every turn, never cached - see session.render_call_sheet's docstring.
        call_sheet = await render_call_sheet(session)
        system = SystemMessage(
            content=f"{build_system_prompt(session.today)}\n\nCurrent call sheet:\n{call_sheet}"
        )
        response = await _invoke_llm(llm, [system, *state["messages"]], session.call_id)
        if response.tool_calls:
            logging.info(
                "[%s] model requested tools: %s", session.call_id, [tc["name"] for tc in response.tool_calls]
            )
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    # ToolNode: given the tool_calls on the last AIMessage, looks each one up by name in
    # `tools`, runs it (awaiting it if it's async, running several in parallel if the model
    # asked for more than one at once), and appends a ToolMessage per call with the result
    # (or, for a caught ValueError, the error text - see _domain_error_message above)
    # tagged with the matching tool_call_id. It's the standard, tested way to do this -
    # hand-rolling it here would just mean re-deriving logic LangGraph already provides.
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=_domain_error_message))

    graph.add_edge(START, "agent")
    # tools_condition inspects the last message: if it has .tool_calls, route to "tools";
    # otherwise the turn is over. Equivalent to "if response.tool_calls: goto tools else
    # end", just as a reusable primitive instead of writing that check by hand.
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    # MemorySaver keeps message history in the process's memory, keyed by thread_id
    # (we use call_id). Good enough for one text session in one process; not durable
    # across a restart - later phases will swap in a persistent checkpointer once a call
    # can span more than one process.
    compiled = graph.compile(checkpointer=MemorySaver())
    return compiled, session
