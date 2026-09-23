from __future__ import annotations

import json
from uuid import UUID

from app.agent.config import AgentSettings
from app.agent.determinism import derive_confidence, derive_severity
from app.agent.grounding import critical_rule_ids, ground_evidence
from app.agent.llm_service import LLMService
from app.agent.nodes import reason_node, validate_node
from app.agent.providers.base import LLMProvider, ProviderCallResult
from app.agent.schemas import DiagnosisResponse, EvidenceItem
from app.agent.state import AgentState
from app.intelligence.models import (
    AnalysisWindow,
    DataQuality,
    Finding,
    HealthContext,
    MetricStatistics,
    ScoreDetails,
)


def _context(*, findings: list[Finding], status: str = "healthy") -> HealthContext:
    return HealthContext(
        vehicle_id="00000000-0000-0000-0000-000000000001",
        generated_at=_now(),
        analysis_window=AnalysisWindow(start=_now(), end=_now(), window_minutes=1.0),
        data_quality=DataQuality(sample_count=40, expected_sample_count=40),
        statistics={},
        trends=[],
        baselines=[],
        findings=findings,
        health_score=100.0,
        health_status=status,
        confidence=0.9,
        score_details=ScoreDetails(score=100.0, status="healthy"),
    )


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _finding(rule_id: str, severity: str = "critical") -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        category="thermal",
        metric="coolant_temperature",
        observed_value=115.0,
        threshold=110.0,
        unit="C",
        message=f"{rule_id} triggered",
    )


def test_severity_follows_highest_finding() -> None:
    context = _context(findings=[_finding("A", "info"), _finding("B", "warning")])
    assert derive_severity(context) == "warning"


def test_severity_falls_back_to_status() -> None:
    assert derive_severity(_context(findings=[])) == "info"
    assert derive_severity(_context(findings=[], status="attention")) == "warning"
    assert derive_severity(_context(findings=[], status="critical")) == "critical"
    assert derive_severity(None) == "info"


def test_confidence_bounded() -> None:
    assert 0.05 <= derive_confidence(_context(findings=[], status="healthy")) <= 0.95


def test_critical_rule_ids() -> None:
    context = _context(findings=[_finding("A", "critical"), _finding("B", "warning")])
    assert critical_rule_ids(context) == ["A"]


def test_ground_evidence_keeps_real_and_drops_fabricated() -> None:
    context = _context(findings=[_finding("COOLANT_TEMP_HIGH")])
    proposed = [
        EvidenceItem(rule_id="COOLANT_TEMP_HIGH"),
        EvidenceItem(rule_id="MADE_UP_RULE"),
    ]
    grounded, warnings = ground_evidence(proposed, context)
    assert [item.rule_id for item in grounded] == ["COOLANT_TEMP_HIGH"]
    assert len(warnings) == 1


def test_ground_evidence_metric_match() -> None:
    context = _context(findings=[])
    context.statistics["battery_voltage"] = MetricStatistics(
        metric="battery_voltage", unit="V", count=40, last=13.5
    )
    proposed = [
        EvidenceItem(metric="battery_voltage", observed_value=13.45),
        EvidenceItem(metric="battery_voltage", observed_value=5.0),
    ]
    grounded, warnings = ground_evidence(proposed, context)
    assert len(grounded) == 1
    assert grounded[0].metric == "battery_voltage"
    assert len(warnings) == 1


def test_ground_evidence_no_context() -> None:
    grounded, warnings = ground_evidence([EvidenceItem(rule_id="X")], None)
    assert grounded == []
    assert warnings


def _guardrail_context(
    *,
    status: str = "healthy",
    findings: list[Finding] | None = None,
    confidence: float = 0.5,
) -> HealthContext:
    return HealthContext(
        vehicle_id="00000000-0000-0000-0000-000000000001",
        generated_at=_now(),
        analysis_window=AnalysisWindow(start=_now(), end=_now(), window_minutes=1.0),
        data_quality=DataQuality(sample_count=40, expected_sample_count=40, coverage_ratio=1.0),
        statistics={},
        trends=[],
        baselines=[],
        findings=findings or [],
        health_score=100.0,
        health_status=status,
        confidence=confidence,
        score_details=ScoreDetails(score=100.0, status=status),
    )


def _llm_reasoning(
    *,
    assessed_severity: str,
    rule_severity: str,
    assessed_confidence: float,
    deterministic_confidence: float,
) -> dict:
    return {
        "summary": "simulated conflicting model interpretation",
        "possible_causes": [],
        "recommended_actions": [],
        "evidence": [],
        "severity_analysis": {
            "assessed_severity": assessed_severity,
            "rule_severity": rule_severity,
            "rationale": "simulated conflicting LLM output",
        },
        "confidence_analysis": {
            "assessed_confidence": assessed_confidence,
            "deterministic_confidence": deterministic_confidence,
            "score_quality": "high",
            "data_quality": "high",
            "rationale": "simulated conflicting LLM output",
            "validation_warnings": [],
        },
        "context_note": "",
    }


def _guardrail_state(*, context: HealthContext, reasoning: dict) -> AgentState:
    return {
        "agent_run_id": "guardrail-run",
        "vehicle_id": UUID("00000000-0000-0000-0000-000000000001"),
        "trigger_type": "USER_QUERY",
        "user_query": "any",
        "vehicle_context": context.model_dump(mode="json"),
        "serialized_context": json.dumps(context.model_dump(mode="json")),
        "context_note": "",
        "severity": derive_severity(context),
        "confidence": derive_confidence(context),
        "context_timestamp": None,
        "execution_metadata": {"rule_ids": []},
        "reasoning": reasoning,
    }


async def test_llm_critical_over_deterministic_info_clamped_to_info() -> None:
    context = _guardrail_context()  # healthy, no findings -> deterministic info
    assert derive_severity(context) == "info"
    reasoning = _llm_reasoning(
        assessed_severity="critical",
        rule_severity="critical",
        assessed_confidence=0.6,
        deterministic_confidence=derive_confidence(context),
    )
    result = await validate_node(_guardrail_state(context=context, reasoning=reasoning))
    response = DiagnosisResponse.model_validate(result["final_response"])

    assert response.severity == "info"
    assert response.diagnosis.severity_analysis.assessed_severity == "info"
    assert (
        "assessed_severity clamped to deterministic vehicle severity"
        in response.diagnosis.confidence_analysis.validation_warnings
    )


async def test_llm_critical_over_deterministic_warning_clamped_to_warning() -> None:
    context = _guardrail_context(status="attention")  # attention -> deterministic warning
    assert derive_severity(context) == "warning"
    reasoning = _llm_reasoning(
        assessed_severity="critical",
        rule_severity="critical",
        assessed_confidence=0.6,
        deterministic_confidence=derive_confidence(context),
    )
    result = await validate_node(_guardrail_state(context=context, reasoning=reasoning))
    response = DiagnosisResponse.model_validate(result["final_response"])

    assert response.severity == "warning"
    assert response.diagnosis.severity_analysis.assessed_severity == "warning"
    assert (
        "assessed_severity clamped to deterministic vehicle severity"
        in response.diagnosis.confidence_analysis.validation_warnings
    )


async def test_llm_info_under_deterministic_critical_keeps_authoritative_critical() -> None:
    context = _guardrail_context(findings=[_finding("COOLANT_TEMP_HIGH", "critical")])
    assert derive_severity(context) == "critical"
    reasoning = _llm_reasoning(
        assessed_severity="info",
        rule_severity="info",
        assessed_confidence=0.6,
        deterministic_confidence=derive_confidence(context),
    )
    result = await validate_node(_guardrail_state(context=context, reasoning=reasoning))
    response = DiagnosisResponse.model_validate(result["final_response"])

    assert response.severity == "critical"
    assert response.diagnosis.severity_analysis.assessed_severity == "info"
    warnings = " ".join(response.diagnosis.confidence_analysis.validation_warnings)
    assert "assessed_severity clamped" not in warnings


async def test_llm_confidence_outside_deviation_clamped_to_deterministic_policy() -> None:
    context = _guardrail_context(status="attention", confidence=0.5)
    deterministic_confidence = derive_confidence(context)
    assert deterministic_confidence == 0.7

    low_reasoning = _llm_reasoning(
        assessed_severity="info",
        rule_severity="info",
        assessed_confidence=0.1,
        deterministic_confidence=deterministic_confidence,
    )
    low = await validate_node(_guardrail_state(context=context, reasoning=low_reasoning))
    low_response = DiagnosisResponse.model_validate(low["final_response"])
    assert low_response.confidence == deterministic_confidence
    assert low_response.diagnosis.confidence_analysis.assessed_confidence == 0.5
    assert (
        "assessed_confidence adjusted to stay within 0.2 of deterministic confidence"
        in low_response.diagnosis.confidence_analysis.validation_warnings
    )

    high_reasoning = _llm_reasoning(
        assessed_severity="info",
        rule_severity="info",
        assessed_confidence=1.0,
        deterministic_confidence=deterministic_confidence,
    )
    high = await validate_node(_guardrail_state(context=context, reasoning=high_reasoning))
    high_response = DiagnosisResponse.model_validate(high["final_response"])
    assert high_response.confidence == deterministic_confidence
    assert high_response.diagnosis.confidence_analysis.assessed_confidence == 0.9
    assert (
        "assessed_confidence adjusted to stay within 0.2 of deterministic confidence"
        in high_response.diagnosis.confidence_analysis.validation_warnings
    )


async def test_llm_confidence_within_deviation_kept_but_final_confidence_authoritative() -> None:
    context = _guardrail_context(status="attention", confidence=0.5)
    deterministic_confidence = derive_confidence(context)
    reasoning = _llm_reasoning(
        assessed_severity="info",
        rule_severity="info",
        assessed_confidence=0.8,
        deterministic_confidence=deterministic_confidence,
    )
    result = await validate_node(_guardrail_state(context=context, reasoning=reasoning))
    response = DiagnosisResponse.model_validate(result["final_response"])

    assert response.diagnosis.confidence_analysis.assessed_confidence == 0.8
    assert response.confidence == deterministic_confidence
    assert "assessed_confidence adjusted" not in " ".join(
        response.diagnosis.confidence_analysis.validation_warnings
    )


class _ConflictingProvider(LLMProvider):
    provider_name = "conflict"

    def __init__(self, settings: AgentSettings, content: str) -> None:
        super().__init__(settings)
        self._content = content

    @property
    def model_name(self) -> str:
        return "conflict-1"

    def _build_chat_model(self):
        raise NotImplementedError

    async def invoke(self, messages):
        return ProviderCallResult(content=self._content)


async def test_conflicting_llm_content_clamped_through_provider_boundary() -> None:
    context = _guardrail_context(status="attention", confidence=0.5)
    deterministic_severity = derive_severity(context)
    deterministic_confidence = derive_confidence(context)
    content = json.dumps(
        _llm_reasoning(
            assessed_severity="critical",
            rule_severity="critical",
            assessed_confidence=0.1,
            deterministic_confidence=deterministic_confidence,
        )
    )
    settings = AgentSettings(
        llm_primary_provider="mock", llm_fallback_provider="", llm_max_retries=0
    )
    llm_service = LLMService(settings, primary_provider=_ConflictingProvider(settings, content))
    state: AgentState = {
        "agent_run_id": "guardrail-e2e",
        "vehicle_id": UUID("00000000-0000-0000-0000-000000000001"),
        "trigger_type": "USER_QUERY",
        "user_query": "any",
        "vehicle_context": context.model_dump(mode="json"),
        "serialized_context": json.dumps(context.model_dump(mode="json")),
        "context_note": "",
        "severity": deterministic_severity,
        "confidence": deterministic_confidence,
        "context_timestamp": None,
        "execution_metadata": {"rule_ids": []},
    }
    reasoned = await reason_node(state, llm_service=llm_service)
    result = await validate_node({**state, **reasoned})
    response = DiagnosisResponse.model_validate(result["final_response"])

    assert response.severity == "warning"
    assert response.diagnosis.severity_analysis.assessed_severity == "warning"
    assert response.diagnosis.confidence_analysis.assessed_confidence == 0.5
    assert response.execution.provider == "conflict"
