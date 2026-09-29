"""Tests backend/agent/llm.py's LangSmith wiring and provider switch. No network call,
no real model gets built - these only check that get_chat_model() picks the right
constructor and fails clearly on bad config, not that a real API call succeeds."""

import os

import pytest

import backend.agent.llm as llm_module
from backend.agent.llm import _configure_langsmith, get_chat_model
from backend.config import settings

pytestmark = pytest.mark.no_db  # no network, no database - runs without Postgres


def test_langsmith_env_vars_are_set_when_tracing_is_on(monkeypatch):
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "fake-key-for-testing")
    monkeypatch.setattr(settings, "langsmith_project", "test-project")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)

    _configure_langsmith()

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "fake-key-for-testing"
    assert os.environ["LANGSMITH_PROJECT"] == "test-project"


def test_langsmith_env_vars_are_left_alone_when_tracing_is_off(monkeypatch):
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    _configure_langsmith()

    assert "LANGSMITH_TRACING" not in os.environ


def test_get_chat_model_rejects_an_unknown_provider(monkeypatch):
    # llm.py did `from backend.constant import AGENT_LLM_PROVIDER`, which copies the value
    # at import time - patching backend.constant afterward wouldn't be seen here, so the
    # module's own bound name has to be patched instead.
    monkeypatch.setattr(llm_module, "AGENT_LLM_PROVIDER", "not-a-real-provider")
    monkeypatch.setattr(settings, "langsmith_tracing", False)

    with pytest.raises(ValueError, match="Unknown AGENT_LLM_PROVIDER"):
        get_chat_model()


def test_nvidia_provider_refuses_to_build_with_the_placeholder_model_id(monkeypatch):
    """NVIDIA_AGENT_MODEL starts as 'REPLACE_ME' until someone copies the real id from
    build.nvidia.com - this must fail loudly, not silently call a nonsense model name."""
    monkeypatch.setattr(llm_module, "AGENT_LLM_PROVIDER", "nvidia")
    monkeypatch.setattr(llm_module, "NVIDIA_AGENT_MODEL", "REPLACE_ME")
    monkeypatch.setattr(settings, "langsmith_tracing", False)

    with pytest.raises(RuntimeError, match="placeholder"):
        get_chat_model()


def test_nvidia_provider_builds_a_model_once_configured(monkeypatch):
    monkeypatch.setattr(llm_module, "AGENT_LLM_PROVIDER", "nvidia")
    monkeypatch.setattr(llm_module, "NVIDIA_AGENT_MODEL", "some-org/some-model")
    monkeypatch.setattr(settings, "nvidia_api_key", "fake-key-for-testing")
    monkeypatch.setattr(settings, "langsmith_tracing", False)

    model = get_chat_model()

    assert model.model_name == "some-org/some-model"


def test_openrouter_provider_refuses_to_build_with_the_placeholder_model_id(monkeypatch):
    """Same guard as NVIDIA's - OPENROUTER_AGENT_MODEL starts as 'REPLACE_ME' until the
    real id is copied from openrouter.ai."""
    monkeypatch.setattr(llm_module, "AGENT_LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(llm_module, "OPENROUTER_AGENT_MODEL", "REPLACE_ME")
    monkeypatch.setattr(settings, "langsmith_tracing", False)

    with pytest.raises(RuntimeError, match="placeholder"):
        get_chat_model()


def test_openrouter_provider_builds_a_model_once_configured(monkeypatch):
    monkeypatch.setattr(llm_module, "AGENT_LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(llm_module, "OPENROUTER_AGENT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key-for-testing")
    monkeypatch.setattr(settings, "langsmith_tracing", False)

    model = get_chat_model()

    assert model.model_name == "nvidia/nemotron-3-ultra-550b-a55b"
