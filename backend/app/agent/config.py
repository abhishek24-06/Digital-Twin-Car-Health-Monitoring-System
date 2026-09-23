"""Configuration for the Phase 4 agent layer.

All LLM/provider values are environment-driven. No model IDs or API keys are
hardcoded; missing configuration surfaces as :class:`AgentConfigurationError`
at provider-build time so the rest of the application can fall back cleanly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Agent/LLM settings loaded from environment variables (.env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_primary_provider: str = "openrouter"
    llm_fallback_provider: str = "groq"

    run_llm_smoke_test: bool = False

    openrouter_api_key: str | None = None
    openrouter_model: str = ""

    groq_api_key: str | None = None
    groq_model: str = ""

    llm_request_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1500

    # Maximum size of the Vehicle Health Context JSON placed into the prompt.
    llm_context_max_chars: int = 24000

    # Repeated critical telemetry for the same vehicle/rule set is
    # de-duplicated for at least this many seconds.
    agent_critical_event_cooldown_seconds: int = 300

    @field_validator("llm_max_retries")
    @classmethod
    def _retries_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("llm_max_retries must be >= 0")
        return value

    @field_validator("llm_request_timeout_seconds")
    @classmethod
    def _timeout_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("llm_request_timeout_seconds must be > 0")
        return value

    @field_validator("llm_temperature")
    @classmethod
    def _temperature_in_range(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("llm_temperature must be within [0, 1]")
        return value


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
