"""The chat model the agent talks through. A plain factory (not a module-level singleton,
unlike menu_cache) so tests and the CLI can each build a fresh instance without import-time
side effects.

Provider is switchable (AGENT_LLM_PROVIDER in backend/constant.py) so one provider running
out of daily quota doesn't block testing - swap the constant, nothing else in graph.py or
tools_binding.py needs to change, since both providers are handed back as a plain
LangChain chat model with .bind_tools() support."""

import os

from langchain_core.language_models.chat_models import BaseChatModel

from backend.config import settings
from backend.constant import (
    AGENT_LLM_PROVIDER,
    AGENT_LLM_TEMPERATURE,
    GROQ_AGENT_MODEL,
    NVIDIA_AGENT_MODEL,
    NVIDIA_BASE_URL,
    OPENROUTER_AGENT_MODEL,
    OPENROUTER_BASE_URL,
)
from logger import logging


def _configure_langsmith() -> None:
    """LangChain traces automatically whenever LANGSMITH_TRACING=true is set in the
    process environment - langchain_core checks for it before every call, no callback or
    handler needs wiring into graph.py. The catch: settings (backend/config.py) reads
    .env into its own fields, it does NOT copy them into os.environ - so without this,
    LANGSMITH_TRACING sitting in .env would never actually reach the SDK that reads it.
    setdefault() so an operator's own real env vars (e.g. in a deployed container) always
    win over .env."""
    if not settings.langsmith_tracing:
        return
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    logging.info("LangSmith tracing enabled (project=%s)", settings.langsmith_project)


def _get_groq_model() -> BaseChatModel:
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=GROQ_AGENT_MODEL,
        temperature=AGENT_LLM_TEMPERATURE,
        api_key=settings.groq_api_key,
    )


def _get_nvidia_model() -> BaseChatModel:
    # NVIDIA's hosted NIM API is OpenAI-compatible, so the plain OpenAI client works
    # against it - just point base_url at NVIDIA instead of OpenAI's own servers.
    from langchain_openai import ChatOpenAI

    if NVIDIA_AGENT_MODEL == "nvidia/nemotron-3-ultra-550b-a55b":
        raise RuntimeError(
            "NVIDIA_AGENT_MODEL in backend/constant.py is still a placeholder. Open "
            "build.nvidia.com, pick a chat model whose card says it supports function "
            "calling / tool use, and copy the exact model id from its API tab."
        )
    return ChatOpenAI(
        model=NVIDIA_AGENT_MODEL,
        temperature=AGENT_LLM_TEMPERATURE,
        api_key=settings.nvidia_api_key,
        base_url=NVIDIA_BASE_URL,
    )


def _get_openrouter_model() -> BaseChatModel:
    # Same OpenAI-compatible shape as NVIDIA above, different host - OpenRouter fronts
    # many providers' models (including some NVIDIA ones) behind one API and one key.
    from langchain_openai import ChatOpenAI

    if OPENROUTER_AGENT_MODEL == "nvidia/nemotron-3-ultra-550b-a55b":
        raise RuntimeError(
            "OPENROUTER_AGENT_MODEL in backend/constant.py is still a placeholder. Open "
            "the model's page on openrouter.ai and copy the exact model id from its API tab "
            "(it may include a ':free' suffix)."
        )
    return ChatOpenAI(
        model=OPENROUTER_AGENT_MODEL,
        temperature=AGENT_LLM_TEMPERATURE,
        api_key=settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
    )


_PROVIDERS = {
    "groq": _get_groq_model,
    "nvidia": _get_nvidia_model,
    "openrouter": _get_openrouter_model,
}


def get_chat_model() -> BaseChatModel:
    _configure_langsmith()
    try:
        builder = _PROVIDERS[AGENT_LLM_PROVIDER]
    except KeyError:
        raise ValueError(
            f"Unknown AGENT_LLM_PROVIDER '{AGENT_LLM_PROVIDER}' - use one of {list(_PROVIDERS)}"
        ) from None
    logging.info("Using LLM provider=%s (temperature %s)", AGENT_LLM_PROVIDER, AGENT_LLM_TEMPERATURE)
    return builder()
