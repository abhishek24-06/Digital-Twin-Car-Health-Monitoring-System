"""Provider selection/config validation (Phase 4)."""

from __future__ import annotations

from app.agent.config import AgentSettings
from app.agent.errors import AgentConfigurationError
from app.agent.providers.base import LLMProvider
from app.agent.providers.groq import GroqProvider
from app.agent.providers.mock import MockLLMProvider
from app.agent.providers.openrouter import OpenRouterProvider


def build_llm_provider(provider_name: str, settings: AgentSettings) -> LLMProvider:
    """Build a provider adapter by name or raise AgentConfigurationError."""
    normalized = (provider_name or "").strip().lower()
    if normalized == "openrouter":
        return OpenRouterProvider(settings)
    if normalized == "groq":
        return GroqProvider(settings)
    if normalized == "mock":
        return MockLLMProvider(settings)
    raise AgentConfigurationError(f"Unsupported LLM provider: {provider_name!r}")
