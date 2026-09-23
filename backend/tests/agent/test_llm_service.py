from __future__ import annotations

import pytest
from langchain_core.messages import BaseMessage, HumanMessage

from app.agent.config import AgentSettings
from app.agent.errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMRateLimitError,
    StructuredOutputError,
)
from app.agent.llm_service import (
    LLMService,
    classify_provider_error,
    extract_json_object,
)
from app.agent.providers.base import LLMProvider, ProviderCallResult
from app.agent.providers.mock import MockLLMProvider

MESSAGES = [HumanMessage(content="hello")]


class _StubError(Exception):
    def __init__(self, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__("stub")


class _FlakyProvider(LLMProvider):
    provider_name = "flaky"

    def __init__(self, settings, *, fail_times: int, status_code: int | None = None) -> None:
        super().__init__(settings)
        self._fail_times = fail_times
        self._status_code = status_code
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "flaky-1"

    def _build_chat_model(self):
        raise NotImplementedError

    async def invoke(self, messages: list[BaseMessage]):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise _StubError(self._status_code)
        return ProviderCallResult(
            content='{"summary": "recovered", "evidence": [], "possible_causes": [], "recommended_actions": [], "severity_analysis": {"assessed_severity": "info", "rule_severity": "info"}, "confidence_analysis": {"assessed_confidence": 0.5, "deterministic_confidence": 0.5}}'
        )


def _agent_settings(**overrides: object) -> AgentSettings:
    base: dict[str, object] = {
        "llm_primary_provider": "mock",
        "llm_max_retries": 1,
    }
    base.update(overrides)
    return AgentSettings(**base)


def test_classify_http_status_codes() -> None:
    provider = "openrouter"
    mapped, kind = classify_provider_error(_StubError(401), provider=provider)
    assert isinstance(mapped, LLMAuthError)
    assert kind.value == "auth"

    mapped, kind = classify_provider_error(_StubError(429), provider=provider)
    assert isinstance(mapped, LLMRateLimitError)
    assert kind.value == "rate_limit"

    mapped, kind = classify_provider_error(_StubError(400), provider=provider)
    assert isinstance(mapped, LLMBadRequestError)
    assert kind.value == "bad_request"


def test_extract_json_object_variants() -> None:
    assert extract_json_object('{"a": 1}')["a"] == 1
    assert extract_json_object('```json\n{"a": 2}\n```')["a"] == 2
    assert extract_json_object('prefix {"a": 3} suffix')["a"] == 3


def test_extract_json_object_invalid_raises() -> None:
    with pytest.raises(StructuredOutputError):
        extract_json_object("no json here")
    with pytest.raises(StructuredOutputError):
        extract_json_object("{broken")
    with pytest.raises(StructuredOutputError):
        extract_json_object("[1, 2, 3]")


async def test_bad_request_not_retried_and_no_fallback() -> None:
    primary = _FlakyProvider(_agent_settings(), fail_times=99, status_code=400)
    service = LLMService(
        _agent_settings(llm_fallback_provider="mock"),
        primary_provider=primary,
        fallback_provider=MockLLMProvider(_agent_settings()),
    )
    with pytest.raises(LLMBadRequestError):
        await service.invoke_structured(MESSAGES)
    assert primary.calls == 1


async def test_auth_error_uses_fallback() -> None:
    primary = _FlakyProvider(_agent_settings(), fail_times=99, status_code=401)
    service = LLMService(
        _agent_settings(llm_fallback_provider="mock"),
        primary_provider=primary,
        fallback_provider=MockLLMProvider(_agent_settings()),
    )
    result = await service.invoke_structured(MESSAGES)
    assert result.fallback_used is True
    assert result.fallback_reason == "llm_authentication"
    assert result.provider == "mock"
    assert primary.calls == 1


async def test_retry_then_fallback_on_persistent_timeout() -> None:
    primary = _FlakyProvider(_agent_settings(), fail_times=2)
    service = LLMService(
        _agent_settings(llm_fallback_provider="mock"),
        primary_provider=primary,
        fallback_provider=MockLLMProvider(_agent_settings()),
    )
    result = await service.invoke_structured(MESSAGES)
    assert primary.calls == 2  # one initial attempt + one retry
    assert result.fallback_used is True
    assert result.provider == "mock"


async def test_retry_recovers_on_primary() -> None:
    primary = _FlakyProvider(_agent_settings(), fail_times=1, status_code=429)
    service = LLMService(
        _agent_settings(llm_fallback_provider="mock"),
        primary_provider=primary,
        fallback_provider=MockLLMProvider(_agent_settings()),
    )
    result = await service.invoke_structured(MESSAGES)
    assert primary.calls == 2
    assert result.provider == "flaky"
    assert result.fallback_used is False
    assert result.attempts == 2


async def test_invalid_structured_output_raises_no_fallback() -> None:
    class _BadOutputProvider(LLMProvider):
        provider_name = "bad-output"

        def __init__(self, settings) -> None:
            super().__init__(settings)

        @property
        def model_name(self) -> str:
            return "bad-output-1"

        def _build_chat_model(self):
            raise NotImplementedError

        async def invoke(self, messages: list[BaseMessage]):
            return ProviderCallResult(content="definitely not json")

    service = LLMService(
        _agent_settings(llm_fallback_provider="mock"),
        primary_provider=_BadOutputProvider(_agent_settings()),
        fallback_provider=MockLLMProvider(_agent_settings()),
    )
    with pytest.raises(StructuredOutputError):
        await service.invoke_structured(MESSAGES)


async def test_provider_structured_output_error_not_retried() -> None:
    calls: list[int] = []

    class _SchemaFailProvider(LLMProvider):
        provider_name = "schema-fail"

        @property
        def model_name(self) -> str:
            return "schema-fail-1"

        def _build_chat_model(self):
            raise NotImplementedError

        async def invoke(self, messages: list[BaseMessage]):
            calls.append(1)
            raise StructuredOutputError("Structured model output failed schema validation")

    service = LLMService(
        _agent_settings(llm_fallback_provider="mock"),
        primary_provider=_SchemaFailProvider(_agent_settings()),
        fallback_provider=MockLLMProvider(_agent_settings()),
    )
    with pytest.raises(StructuredOutputError, match="failed schema validation"):
        await service.invoke_structured(MESSAGES)
    assert calls == [1]


async def test_mock_structured_end_to_end() -> None:
    service = LLMService(_agent_settings())
    result = await service.invoke_structured(MESSAGES)
    assert result.provider == "mock"
    assert result.model == "mock-1"
    assert result.fallback_used is False
    import json

    assert json.loads(result.content)["severity_analysis"]["assessed_severity"] == "info"
