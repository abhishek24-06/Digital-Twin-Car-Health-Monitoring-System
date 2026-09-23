from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.config import AgentSettings, get_agent_settings

_AGENT_ENV_VARS = (
    "LLM_PRIMARY_PROVIDER",
    "LLM_FALLBACK_PROVIDER",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "LLM_REQUEST_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "LLM_TEMPERATURE",
    "LLM_MAX_TOKENS",
    "LLM_CONTEXT_MAX_CHARS",
    "AGENT_CRITICAL_EVENT_COOLDOWN_SECONDS",
)


def test_defaults_match_phase4_spec(monkeypatch) -> None:
    for name in _AGENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    settings = AgentSettings(_env_file=None)
    assert settings.llm_primary_provider == "openrouter"
    assert settings.llm_fallback_provider == "groq"
    assert settings.openrouter_model == ""
    assert settings.groq_model == ""
    assert settings.llm_request_timeout_seconds == 60.0
    assert settings.llm_max_retries == 2
    assert settings.llm_temperature == 0.1
    assert settings.llm_max_tokens == 1500
    assert settings.llm_context_max_chars == 24000
    assert settings.agent_critical_event_cooldown_seconds == 300


def test_negative_retries_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentSettings(llm_max_retries=-1)


def test_non_positive_timeout_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentSettings(llm_request_timeout_seconds=0.0)


def test_temperature_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentSettings(llm_temperature=1.5)


def test_get_agent_settings_cached() -> None:
    assert get_agent_settings() is get_agent_settings()
