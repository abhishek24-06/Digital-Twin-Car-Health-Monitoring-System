"""Groq LLM provider adapter (OpenAI-compatible API)."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.agent.config import AgentSettings
from app.agent.errors import AgentConfigurationError
from app.agent.providers.base import LLMProvider

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(LLMProvider):
    """LLM served by Groq's hosted OpenAI-compatible endpoint."""

    provider_name = "groq"

    def __init__(self, settings: AgentSettings) -> None:
        super().__init__(settings)
        if not settings.groq_api_key:
            raise AgentConfigurationError("Groq API key is not configured")
        if not settings.groq_model:
            raise AgentConfigurationError("Groq model is not configured")

    @property
    def model_name(self) -> str:
        return self._settings.groq_model

    def _build_chat_model(self) -> BaseChatModel:
        return ChatOpenAI(
            model=self.model_name,
            openai_api_key=self._settings.groq_api_key,
            openai_api_base=GROQ_BASE_URL,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
            max_retries=0,
            request_timeout=self._settings.llm_request_timeout_seconds,
        )
