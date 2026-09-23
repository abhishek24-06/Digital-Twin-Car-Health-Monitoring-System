"""Error taxonomy for the Phase 4 agent layer.

Provider exceptions are normalized into these classes before they leave
:class:`app.agent.llm_service.LLMService`. Message text is sanitized so that
API keys and authorization material never reach logs or API responses.
"""

from __future__ import annotations

from app.core.exceptions import AppError


class AgentError(AppError):
    """Base class for all Phase 4 agent errors."""

    error_code = "agent_error"

    def __init__(self, message: str = "Agent operation failed") -> None:
        super().__init__(message)


class AgentConfigurationError(AgentError):
    """The agent is not configured correctly (missing model/provider/key)."""

    error_code = "agent_configuration_error"


class LLMProviderError(AgentError):
    """A language-model provider call failed after retries/fallback."""

    error_code = "llm_provider_error"

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        self.provider = provider
        super().__init__(message)


class LLMTimeoutError(LLMProviderError):
    """The provider did not respond within the configured timeout."""

    error_code = "llm_timeout"


class LLMRateLimitError(LLMProviderError):
    """The provider is rate limiting requests."""

    error_code = "llm_rate_limited"


class LLMAuthError(LLMProviderError):
    """The provider rejected the configured credentials."""

    error_code = "llm_authentication"


class LLMProviderUnavailableError(LLMProviderError):
    """Connection/server failure made the provider unusable."""

    error_code = "llm_provider_unavailable"


class LLMBadRequestError(LLMProviderError):
    """The request itself was rejected (invalid model/parameters)."""

    error_code = "llm_bad_request"


class StructuredOutputError(AgentError):
    """The model output could not be validated against the schema."""

    error_code = "structured_output_invalid"


class GraphExecutionError(AgentError):
    """The LangGraph workflow failed to complete."""

    error_code = "graph_execution_error"
