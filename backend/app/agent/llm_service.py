"""LLM invocation service with retries, fallback routing and JSON extraction.

Provider failures are normalized to the agent error taxonomy. Retryable
failures (timeout, rate limit, connection, server, unknown) are retried with
exponential backoff; authentication/config failures skip retries but may use
the fallback provider; bad requests and invalid structured output are never
retried or re-routed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from langchain_core.messages import BaseMessage

from app.agent.config import AgentSettings
from app.agent.errors import (
    AgentConfigurationError,
    AgentError,
    LLMAuthError,
    LLMBadRequestError,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    StructuredOutputError,
)
from app.agent.providers import LLMProvider, ProviderCallResult, build_llm_provider

logger = logging.getLogger(__name__)

_BACKOFF_BASE_SECONDS = 0.2
_BACKOFF_MAX_SECONDS = 2.0


class ProviderFailureKind(StrEnum):
    """Normalized provider failure categories used for routing decisions."""

    AUTH = "auth"
    BAD_REQUEST = "bad_request"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    CONNECTION = "connection"
    SERVER = "server"
    UNKNOWN = "unknown"


_FALLBACK_ELIGIBLE: set[ProviderFailureKind] = {
    ProviderFailureKind.TIMEOUT,
    ProviderFailureKind.RATE_LIMIT,
    ProviderFailureKind.CONNECTION,
    ProviderFailureKind.SERVER,
    ProviderFailureKind.UNKNOWN,
    ProviderFailureKind.AUTH,
}


@dataclass(slots=True)
class StructuredLLMResult:
    """A successfully parsed structured response from the provider stack."""

    content: str
    provider: str
    model: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 1


_NORMALIZED_ERROR_KINDS: dict[type[LLMProviderError], ProviderFailureKind] = {
    LLMTimeoutError: ProviderFailureKind.TIMEOUT,
    LLMRateLimitError: ProviderFailureKind.RATE_LIMIT,
    LLMAuthError: ProviderFailureKind.AUTH,
    LLMProviderUnavailableError: ProviderFailureKind.CONNECTION,
    LLMBadRequestError: ProviderFailureKind.BAD_REQUEST,
}


def classify_provider_error(
    exc: Exception, *, provider: str
) -> tuple[LLMProviderError, ProviderFailureKind]:
    """Map arbitrary provider exceptions onto the app error taxonomy."""
    if isinstance(exc, LLMProviderError):
        kind = _NORMALIZED_ERROR_KINDS.get(type(exc), ProviderFailureKind.UNKNOWN)
        return exc, kind
    if isinstance(exc, (asyncio.TimeoutError,)) or _type_name(exc) == "APITimeoutError":
        return LLMTimeoutError(
            "LLM provider timed out", provider=provider
        ), ProviderFailureKind.TIMEOUT

    status_code = _status_code(exc)
    type_name = _type_name(exc)

    if status_code == 429 or type_name == "RateLimitError":
        return (
            LLMRateLimitError("LLM provider is rate limiting requests", provider=provider),
            ProviderFailureKind.RATE_LIMIT,
        )
    if status_code in (401, 403) or type_name in {
        "AuthenticationError",
        "PermissionDeniedError",
        "SignatureVerificationError",
    }:
        return LLMAuthError(
            "LLM provider rejected credentials", provider=provider
        ), ProviderFailureKind.AUTH
    if status_code == 400 or type_name == "BadRequestError":
        return LLMBadRequestError(
            "LLM provider rejected the request", provider=provider
        ), ProviderFailureKind.BAD_REQUEST
    if type_name == "APIConnectionError" or status_code in {502, 503, 504}:
        return (
            LLMProviderUnavailableError("LLM provider is unavailable", provider=provider),
            ProviderFailureKind.CONNECTION,
        )
    if status_code is not None and status_code >= 500:
        return (
            LLMProviderUnavailableError("LLM provider reported a server error", provider=provider),
            ProviderFailureKind.SERVER,
        )
    return (
        LLMProviderUnavailableError("LLM provider call failed", provider=provider),
        ProviderFailureKind.UNKNOWN,
    )


class LLMService:
    """Retries, fallback routing and structured extraction for LLM calls."""

    def __init__(
        self,
        settings: AgentSettings,
        *,
        primary_provider: LLMProvider | None = None,
        fallback_provider: LLMProvider | None = None,
    ) -> None:
        self._settings = settings
        self._primary: LLMProvider | None = primary_provider
        self._fallback: LLMProvider | None = fallback_provider

    async def invoke_structured(self, messages: list[BaseMessage]) -> StructuredLLMResult:
        """Call the primary provider, retry, then fall back; extract JSON."""
        primary = self._resolve_primary()
        fallback = self._resolve_fallback()

        try:
            result, attempts = await self._invoke_with_retries(primary, messages)
        except AgentConfigurationError as exc:
            if fallback is None:
                raise
            logger.warning("primary provider misconfigured; falling back: %s", exc)
            return await self._invoke_fallback(fallback, messages, fallback_reason=exc.error_code)
        except LLMProviderError as primary_error:
            return await self._invoke_after_primary_failure(
                primary_error, primary, fallback, messages
            )
        return self._to_structured(result, provider=primary, attempts=attempts)

    async def _invoke_after_primary_failure(
        self,
        primary_error: LLMProviderError,
        primary: LLMProvider,
        fallback: LLMProvider | None,
        messages: list[BaseMessage],
    ) -> StructuredLLMResult:
        kind = classify_provider_error(primary_error, provider=primary.provider_name)[1]
        if kind not in _FALLBACK_ELIGIBLE or fallback is None:
            raise primary_error
        return await self._invoke_fallback(
            fallback, messages, fallback_reason=primary_error.error_code
        )

    async def _invoke_fallback(
        self,
        fallback: LLMProvider,
        messages: list[BaseMessage],
        *,
        fallback_reason: str,
    ) -> StructuredLLMResult:
        try:
            result, attempts = await self._invoke_with_retries(fallback, messages)
        except LLMProviderError as exc:
            raise exc
        return self._to_structured(
            result,
            provider=fallback,
            fallback_used=True,
            fallback_reason=fallback_reason,
            attempts=attempts,
        )

    async def _invoke_with_retries(
        self, provider: LLMProvider, messages: list[BaseMessage]
    ) -> tuple[ProviderCallResult, int]:
        last_error: AgentError | None = None
        max_attempts = self._settings.llm_max_retries + 1
        for attempt in range(max_attempts):
            try:
                result = await asyncio.wait_for(
                    provider.invoke(messages),
                    timeout=self._settings.llm_request_timeout_seconds,
                )
                if last_error is not None:
                    logger.warning(
                        "LLM recovered after %s failed attempt(s) on %s",
                        attempt,
                        provider.provider_name,
                    )
                return result, attempt + 1
            except AgentConfigurationError as exc:
                last_error = exc
                break
            except TimeoutError:
                last_error = LLMTimeoutError(
                    "LLM provider timed out", provider=provider.provider_name
                )
            except AgentError as exc:
                last_error = exc
            except Exception as exc:  # noqa: BLE001
                last_error, _ = classify_provider_error(exc, provider=provider.provider_name)

            if last_error is None:
                continue
            if last_error.error_code in _not_retried_codes(last_error, provider):
                break
            if attempt < max_attempts - 1:
                await asyncio.sleep(min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * (2**attempt)))

        if last_error is None:
            last_error = LLMProviderUnavailableError(
                "LLM provider call failed", provider=provider.provider_name
            )
        raise last_error

    @staticmethod
    def _to_structured(
        result: ProviderCallResult,
        *,
        provider: LLMProvider,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        attempts: int = 1,
    ) -> StructuredLLMResult:
        payload = extract_json_object(result.content)
        return StructuredLLMResult(
            content=json.dumps(payload, ensure_ascii=False),
            provider=provider.provider_name,
            model=provider.model_name,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            attempts=attempts,
        )

    def _resolve_primary(self) -> LLMProvider:
        if self._primary is None:
            self._primary = build_llm_provider(self._settings.llm_primary_provider, self._settings)
        return self._primary

    def _resolve_fallback(self) -> LLMProvider | None:
        if self._fallback is not None:
            return self._fallback
        if not (self._settings.llm_fallback_provider or "").strip():
            return None
        try:
            self._fallback = build_llm_provider(
                self._settings.llm_fallback_provider, self._settings
            )
        except AgentConfigurationError:
            logger.warning(
                "fallback provider not configured properly: %s",
                self._settings.llm_fallback_provider,
            )
            self._fallback = None
        return self._fallback


def _not_retried_codes(error: AgentError, provider: LLMProvider) -> set[str]:
    """Error codes that never benefit from another attempt on the same provider."""
    if error.error_code == "llm_bad_request":
        return {error.error_code}
    if error.error_code == "llm_authentication":
        return {error.error_code}
    if error.error_code == "agent_configuration_error":
        return {error.error_code}
    if error.error_code == "structured_output_invalid":
        return {error.error_code}
    return set()


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first top-level JSON object from model output."""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = _strip_fence(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise StructuredOutputError("Model output contained no JSON object")
    try:
        payload = json.loads(stripped[start : end + 1])
    except (json.JSONDecodeError, ValueError) as exc:
        raise StructuredOutputError(f"Model output was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise StructuredOutputError("Model output JSON was not an object")
    return payload


def _strip_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _type_name(exc: Exception) -> str:
    return type(exc).__name__
