"""OpenRouter-hosted LLM provider adapter (OpenAI-compatible API)."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.agent.config import AgentSettings
from app.agent.errors import AgentConfigurationError
from app.agent.providers.base import LLMProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    """LLM routed through the OpenRouter hosted gateway."""

    provider_name = "openrouter"

    def __init__(self, settings: AgentSettings) -> None:
        super().__init__(settings)
        if not settings.openrouter_api_key:
            raise AgentConfigurationError("OpenRouter API key is not configured")
        if not settings.openrouter_model:
            raise AgentConfigurationError("OpenRouter model is not configured")

    @property
    def model_name(self) -> str:
        return self._settings.openrouter_model

    def _build_chat_model(self) -> BaseChatModel:
        return ChatOpenAI(
            model=self.model_name,
            openai_api_key=self._settings.openrouter_api_key,
            openai_api_base=OPENROUTER_BASE_URL,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
            max_retries=0,
            request_timeout=self._settings.llm_request_timeout_seconds,
        )
