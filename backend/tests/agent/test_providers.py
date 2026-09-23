from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI

from app.agent.config import AgentSettings
from app.agent.errors import AgentConfigurationError, StructuredOutputError
from app.agent.llm_service import extract_json_object
from app.agent.prompts import build_query_messages
from app.agent.providers.base import LLMProvider
from app.agent.providers.factory import build_llm_provider
from app.agent.providers.groq import GROQ_BASE_URL, GroqProvider
from app.agent.providers.mock import MockLLMProvider
from app.agent.providers.openrouter import OPENROUTER_BASE_URL, OpenRouterProvider
from app.agent.schemas import (
    ConfidenceAnalysis,
    DiagnosisContent,
    EvidenceItem,
    Hypothesis,
    RecommendedAction,
    SeverityAnalysis,
)

MESSAGES = [HumanMessage(content="hello")]


def _valid_diagnosis() -> DiagnosisContent:
    return DiagnosisContent(
        summary="Cooling system needs inspection",
        possible_causes=[Hypothesis(cause="water pump degradation", likelihood="high")],
        recommended_actions=[
            RecommendedAction(action="inspect coolant loop", priority="high", category="mechanical")
        ],
        evidence=[
            EvidenceItem(
                rule_id="COOLANT_TEMP_HIGH",
                metric="coolant_temperature",
                observed_value=113.5,
                threshold=110.0,
                unit="C",
                message="Coolant temperature above threshold",
                severity="critical",
            )
        ],
        severity_analysis=SeverityAnalysis(assessed_severity="warning", rule_severity="critical"),
        confidence_analysis=ConfidenceAnalysis(
            assessed_confidence=0.8,
            deterministic_confidence=0.9,
            score_quality="high",
            data_quality="high",
            rationale="grounded in telemetry",
        ),
        context_note="reviewed before advising",
    )


class _FakeStructuredOutput:
    def __init__(self, result: dict) -> None:
        self._result = result

    async def ainvoke(self, messages: list[BaseMessage]) -> dict:
        return self._result


class _FakeChatModel:
    def __init__(self, result: dict) -> None:
        self._result = result
        self.structured_calls: list[tuple[tuple, dict]] = []

    def with_structured_output(self, *args, **kwargs):
        self.structured_calls.append((args, kwargs))
        return _FakeStructuredOutput(self._result)


class _StructProvider(LLMProvider):
    provider_name = "struct-test"

    def __init__(self, settings: AgentSettings, chat_model: _FakeChatModel) -> None:
        super().__init__(settings)
        self._chat_model = chat_model

    @property
    def model_name(self) -> str:
        return "struct-1"

    def _build_chat_model(self):
        return self._chat_model


def _raw_message(usage: dict | None = None) -> AIMessage:
    return AIMessage(
        content="",
        usage_metadata=usage or {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
    )


def test_unknown_provider_rejected() -> None:
    with pytest.raises(AgentConfigurationError, match="Unsupported LLM provider"):
        build_llm_provider("nope", AgentSettings())


def test_openrouter_requires_key_and_model(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    with pytest.raises(AgentConfigurationError, match="API key"):
        build_llm_provider("openrouter", AgentSettings(openrouter_api_key=None, _env_file=None))
    with pytest.raises(AgentConfigurationError, match="model"):
        build_llm_provider("openrouter", AgentSettings(openrouter_api_key="key", _env_file=None))


def test_groq_requires_key_and_model(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    with pytest.raises(AgentConfigurationError, match="API key"):
        build_llm_provider("groq", AgentSettings(groq_api_key=None, _env_file=None))
    with pytest.raises(AgentConfigurationError, match="model"):
        build_llm_provider("groq", AgentSettings(groq_api_key="key", _env_file=None))


def test_factory_builds_expected_types() -> None:
    settings = AgentSettings(openrouter_api_key="key", openrouter_model="provider/model")
    assert isinstance(build_llm_provider("openrouter", settings), OpenRouterProvider)
    groq_settings = AgentSettings(groq_api_key="key", groq_model="groq/model")
    assert isinstance(build_llm_provider("groq", groq_settings), GroqProvider)
    assert isinstance(build_llm_provider("mock", settings), MockLLMProvider)


async def test_mock_provider_is_deterministic_and_parsable() -> None:
    provider = MockLLMProvider(AgentSettings())
    context = {
        "vehicle_id": "00000000-0000-0000-0000-000000000001",
        "health_status": "attention",
        "confidence": 0.8,
        "findings": [
            {
                "rule_id": "COOLANT_TEMP_HIGH",
                "severity": "critical",
                "category": "thermal",
                "metric": "coolant_temperature",
                "observed_value": 115.0,
                "threshold": 110.0,
                "unit": "C",
                "message": "Coolant temperature above threshold",
            }
        ],
        "statistics": {},
    }
    import json

    messages = build_query_messages(context_json=json.dumps(context), user_query="why is it hot?")
    first = await provider.invoke(messages)
    second = await provider.invoke(messages)
    assert first.content == second.content

    payload = json.loads(first.content)
    assert payload["severity_analysis"]["assessed_severity"] == "critical"
    assert payload["evidence"][0]["rule_id"] == "COOLANT_TEMP_HIGH"
    assert payload["possible_causes"][0]["cause"].startswith("Possible cause")


async def test_structured_provider_success_returns_canonical_json() -> None:
    parsed = _valid_diagnosis()
    model = _FakeChatModel({"raw": _raw_message(), "parsed": parsed, "parsing_error": None})
    provider = _StructProvider(AgentSettings(), model)

    result = await provider.invoke(MESSAGES)

    payload = extract_json_object(result.content)
    assert payload == parsed.model_dump(mode="json")
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    assert result.latency_ms >= 0.0
    assert len(model.structured_calls) == 1
    schema, options = model.structured_calls[0]
    assert schema == (DiagnosisContent,)
    assert options == {"method": "function_calling", "include_raw": True}


async def test_structured_provider_accepts_parsed_dict() -> None:
    model = _FakeChatModel(
        {
            "raw": _raw_message(),
            "parsed": _valid_diagnosis().model_dump(),
            "parsing_error": None,
        }
    )
    provider = _StructProvider(AgentSettings(), model)

    result = await provider.invoke(MESSAGES)

    assert extract_json_object(result.content)["summary"] == "Cooling system needs inspection"


async def test_structured_provider_rejects_prose_output() -> None:
    model = _FakeChatModel(
        {
            "raw": _raw_message(),
            "parsed": None,
            "parsing_error": ValueError("no tool call emitted"),
        }
    )
    provider = _StructProvider(AgentSettings(), model)
    with pytest.raises(StructuredOutputError, match="failed schema validation"):
        await provider.invoke(MESSAGES)


async def test_structured_provider_rejects_invalid_json_fallback() -> None:
    model = _FakeChatModel(
        {
            "raw": AIMessage(content="sorry, I cannot output that shape"),
            "parsed": None,
            "parsing_error": ValueError("parse failure"),
        }
    )
    provider = _StructProvider(AgentSettings(), model)
    with pytest.raises(StructuredOutputError, match="failed schema validation"):
        await provider.invoke(MESSAGES)


async def test_structured_provider_rejects_type_violating_parsed_payload() -> None:
    model = _FakeChatModel(
        {"raw": _raw_message(), "parsed": {"summary": 123}, "parsing_error": None}
    )
    provider = _StructProvider(AgentSettings(), model)
    with pytest.raises(StructuredOutputError, match="failed schema validation"):
        await provider.invoke(MESSAGES)


async def test_structured_provider_accepts_schema_valid_content_fallback() -> None:
    valid_json = json.dumps(_valid_diagnosis().model_dump(mode="json"))
    model = _FakeChatModel(
        {
            "raw": AIMessage(content=valid_json),
            "parsed": None,
            "parsing_error": ValueError("parser plumbing mismatch on endpoint"),
        }
    )
    provider = _StructProvider(AgentSettings(), model)

    result = await provider.invoke(MESSAGES)

    assert extract_json_object(result.content)["summary"] == "Cooling system needs inspection"


async def test_structured_provider_truncated_json_reports_actual_failure() -> None:
    # Reproduces the live OpenRouter failure: the model emits the schema JSON
    # as free text (parsed=None, parsing_error=None because no tool call was
    # emitted) and the completion is cut off at max_tokens mid-document.
    truncated = (
        '{"summary": "Vehicle shows healthy status but several metrics need attention", '
        '"possible_causes": [{"cause": "Engine performance degradation", "likelihood": "medium", '
        '"matching_evidence": ["rpm current 1335.2 vs center 2024.5"], '
        '"recommended_actions": ["inspect"]}], "recommended_actions": [], "evidence": [], '
        '"severity_analysis": {"assessed_severity": "info", "rule_severity": "info", '
        '"rationale": "depressed RPM and speed"}, '
        '"confidence_analysis": {"assessed_confidence": 0.5, "deterministic_confidence": 0.5, '
        '"score_quality": "medium", "data_quality": "medium", '
        '"rationale": "telemetry gaps"'
    )
    raw = AIMessage(content=truncated, response_metadata={"finish_reason": "length"})
    model = _FakeChatModel({"raw": raw, "parsed": None, "parsing_error": None})
    provider = _StructProvider(AgentSettings(), model)

    with pytest.raises(StructuredOutputError) as excinfo:
        await provider.invoke(MESSAGES)

    message = str(excinfo.value)
    assert "failed schema validation" in message
    assert "truncated" in message
    assert "llm_max_tokens" in message
    assert len(message) < 600


async def test_structured_output_error_never_leaks_payload() -> None:
    secret = "test-openrouter-api-key"
    bad_json = '{"summary": "unrelated text before the provider error", "possible_causes": ['
    raw = AIMessage(content=bad_json)
    model = _FakeChatModel(
        {
            "raw": raw,
            "parsed": None,
            "parsing_error": ValueError("provider rejected token " + secret),
        }
    )
    provider = _StructProvider(AgentSettings(), model)

    with pytest.raises(StructuredOutputError) as excinfo:
        await provider.invoke(MESSAGES)

    message = str(excinfo.value)
    assert "***" in message
    assert secret not in message
    assert "failed schema validation" in message
    assert len(message) < 600


async def test_structured_output_error_carries_provider_and_model() -> None:
    truncated = (
        '{"summary": "Vehicle shows healthy status but several metrics need attention", '
        '"possible_causes": [], "recommended_actions": [], "evidence": [], '
        '"severity_analysis": {"assessed_severity": "info", "rule_severity": "info", '
        '"rationale": "incomplete", "confidence_analysis": {"assessed_confidence": 0.5, '
        '"deterministic_confidence": 0.5, "score_quality": "medium", "data_quality": "medium", '
        '"rationale": "telemetry gaps"'
    )
    raw = AIMessage(content=truncated, response_metadata={"finish_reason": "length"})
    model = _FakeChatModel({"raw": raw, "parsed": None, "parsing_error": None})
    provider = _StructProvider(AgentSettings(), model)

    with pytest.raises(StructuredOutputError) as excinfo:
        await provider.invoke(MESSAGES)

    assert excinfo.value.provider == "struct-test"
    assert excinfo.value.model == "struct-1"
    assert "struct-test" not in str(excinfo.value)


def test_openrouter_structured_output_configuration(monkeypatch) -> None:
    settings = AgentSettings(
        openrouter_api_key="sk-test-1234567890abcdef",
        openrouter_model="acme/model",
    )
    provider = OpenRouterProvider(settings)
    model = provider.get_chat_model()
    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base == OPENROUTER_BASE_URL
    assert model.model_name == "acme/model"

    captured: dict = {}

    def fake_with_structured_output(self, schema, **kwargs):
        captured["schema"] = schema
        captured["kwargs"] = kwargs
        return "STRUCTURED"

    monkeypatch.setattr(ChatOpenAI, "with_structured_output", fake_with_structured_output)
    result = provider._structured_model(model)
    assert result == "STRUCTURED"
    assert captured["schema"] is DiagnosisContent
    assert captured["kwargs"]["method"] == "function_calling"
    assert captured["kwargs"]["include_raw"] is True


def test_groq_structured_output_configuration(monkeypatch) -> None:
    settings = AgentSettings(groq_api_key="sk-test-1234567890abcdef", groq_model="llama/model")
    provider = GroqProvider(settings)
    model = provider.get_chat_model()
    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base == GROQ_BASE_URL
    assert model.model_name == "llama/model"

    captured: dict = {}

    def fake_with_structured_output(self, schema, **kwargs):
        captured["schema"] = schema
        captured["kwargs"] = kwargs
        return "STRUCTURED"

    monkeypatch.setattr(ChatOpenAI, "with_structured_output", fake_with_structured_output)
    result = provider._structured_model(model)
    assert result == "STRUCTURED"
    assert captured["schema"] is DiagnosisContent
    assert captured["kwargs"]["method"] == "function_calling"
    assert captured["kwargs"]["include_raw"] is True


async def test_openrouter_invoke_uses_structured_normalization(monkeypatch) -> None:
    settings = AgentSettings(
        openrouter_api_key="sk-test-1234567890abcdef",
        openrouter_model="acme/model",
    )
    provider = OpenRouterProvider(settings)
    parsed = _valid_diagnosis()
    structured_result = {"raw": _raw_message(), "parsed": parsed, "parsing_error": None}
    provider._structured_model = lambda chat_model: _FakeStructuredOutput(structured_result)

    result = await provider.invoke(MESSAGES)

    assert extract_json_object(result.content) == parsed.model_dump(mode="json")
    assert result.input_tokens == 12
    assert result.output_tokens == 7


async def test_groq_invoke_uses_structured_normalization(monkeypatch) -> None:
    settings = AgentSettings(groq_api_key="sk-test-1234567890abcdef", groq_model="llama/model")
    provider = GroqProvider(settings)
    parsed = _valid_diagnosis()
    structured_result = {"raw": _raw_message(), "parsed": parsed, "parsing_error": None}
    provider._structured_model = lambda chat_model: _FakeStructuredOutput(structured_result)

    result = await provider.invoke(MESSAGES)

    assert extract_json_object(result.content) == parsed.model_dump(mode="json")
    assert result.input_tokens == 12
    assert result.output_tokens == 7
