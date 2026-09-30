"""Deterministic in-process provider for tests and offline demos.

The mock parses the Vehicle Health Context embedded in the user message and
derives its diagnosis from it using the deterministic walkthrough, so graphs,
grounding, persistence and API tests get realistic, repeatable output without
any network access or API keys. When the context cannot be parsed as a full
HealthContext, a conservative fallback mirrors whatever top-level values were
present.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from app.agent.determinism import (
    SEVERITY_RANK,
    derive_confidence,
    derive_data_quality,
    derive_score_quality,
    derive_severity,
)
from app.agent.providers.base import LLMProvider, ProviderCallResult
from app.intelligence.models import HealthContext


class MockLLMProvider(LLMProvider):
    """Deterministic provider that never performs a network call."""

    provider_name = "mock"

    @property
    def model_name(self) -> str:
        return "mock-1"

    def _build_chat_model(self) -> BaseChatModel:
        raise NotImplementedError("MockLLMProvider performs no network calls")

    def get_chat_model(self) -> BaseChatModel:
        raise NotImplementedError("MockLLMProvider performs no network calls")

    async def invoke(self, messages: list[BaseMessage]) -> ProviderCallResult:
        started = time.perf_counter()
        payload = _build_mock_payload(_extract_context(messages))
        _inject_mock_manufacturer_guidance(payload, _sources_available(messages))
        latency_ms = (time.perf_counter() - started) * 1000.0
        return ProviderCallResult(
            content=json.dumps(payload, ensure_ascii=False),
            latency_ms=latency_ms,
        )


def _extract_context(messages: list[BaseMessage]) -> dict[str, Any] | None:
    """Locate the serialized health context inside the human message."""
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            continue
        start = 0
        while True:
            open_idx = content.find("{", start)
            if open_idx == -1:
                break
            close_idx = content.rfind("}")
            if close_idx > open_idx:
                try:
                    payload = json.loads(content[open_idx : close_idx + 1])
                except (json.JSONDecodeError, ValueError):
                    payload = None
                if isinstance(payload, dict) and "health_status" in payload:
                    return payload
            start = open_idx + 1
    return None


def _sources_available(messages: list[BaseMessage]) -> int:
    """Count the numbered manufacturer source lines supplied to the model."""
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            continue
        marker = "Sources:\n"
        if marker not in content:
            continue
        tail = content.split(marker, 1)[1]
        return sum(
            1 for line in tail.splitlines() if line.strip().split(".", 1)[0].strip().isdigit()
        )
    return 0


def _inject_mock_manufacturer_guidance(payload: dict[str, Any], sources: int) -> None:
    """Deterministically echo the RAG evidence into the mock diagnosis.

    Mirrors what an instruct-following model would do once manufacturer
    guidance is part of the prompt: reference the first supplied source.
    """
    if sources <= 0:
        payload["manufacturer_guidance"] = ""
        payload["cited_sources"] = []
        return
    payload["manufacturer_guidance"] = (
        "Mock manufacturer guidance: follow the supplied source materials; "
        "no additional manufacturer claims are made."
    )
    payload["cited_sources"] = [1]


def _build_mock_payload(context: dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {
            "summary": "Mock analysis: no Vehicle Health Context was provided.",
            "possible_causes": [],
            "recommended_actions": [],
            "evidence": [],
            "severity_analysis": {
                "assessed_severity": "info",
                "rule_severity": "info",
                "rationale": "Mock provider mirrors deterministic severity.",
            },
            "confidence_analysis": {
                "assessed_confidence": 0.0,
                "deterministic_confidence": 0.0,
                "score_quality": "low",
                "data_quality": "low",
                "rationale": "Mock provider mirrors deterministic confidence.",
                "validation_warnings": [],
            },
            "context_note": "",
        }

    try:
        model = HealthContext.model_validate(context)
    except Exception:
        model = None

    if model is not None:
        severity = derive_severity(model)
        confidence = derive_confidence(model)
        score_quality = derive_score_quality(model)
        data_quality = derive_data_quality(model)
        findings = [
            {
                "rule_id": finding.rule_id,
                "metric": finding.metric,
                "observed_value": finding.observed_value,
                "threshold": finding.threshold,
                "unit": finding.unit,
                "message": finding.message,
                "severity": finding.severity,
            }
            for finding in model.findings
        ]
    else:
        raw_findings = context.get("findings") or []
        severity = _severity_from_raw(raw_findings, context.get("health_status"))
        confidence = _confidence_from_raw(context.get("confidence"))
        score_quality = "medium" if confidence >= 0.5 else "low"
        data_quality = score_quality
        findings = [
            {
                "rule_id": finding.get("rule_id"),
                "metric": finding.get("metric"),
                "observed_value": finding.get("observed_value"),
                "threshold": finding.get("threshold"),
                "unit": finding.get("unit"),
                "message": finding.get("message") or "",
                "severity": finding.get("severity"),
            }
            for finding in raw_findings
        ]

    causes = [
        {
            "cause": f"Possible cause related to the {finding['category']} finding ({finding['rule_id']})"
            if finding.get("category")
            else f"Possible cause related to finding {finding['rule_id']}",
            "likelihood": _likelihood_from_severity(finding.get("severity")),
            "matching_evidence": [finding["rule_id"]] if finding.get("rule_id") else [],
            "recommended_actions": [
                "Verify the underlying condition on site and re-check telemetry"
            ],
        }
        for finding in findings[:5]
    ]
    return {
        "summary": (
            f"Mock analysis: {len(findings)} finding(s); "
            f"vehicle status is {context.get('health_status', 'unknown')}."
        ),
        "possible_causes": causes,
        "recommended_actions": [
            {
                "action": "Operate within documented limits and continue monitoring telemetry",
                "priority": "medium",
                "category": "operator",
            }
        ],
        "evidence": findings,
        "severity_analysis": {
            "assessed_severity": severity,
            "rule_severity": severity,
            "rationale": "Mock provider mirrors deterministic severity.",
        },
        "confidence_analysis": {
            "assessed_confidence": confidence,
            "deterministic_confidence": confidence,
            "score_quality": score_quality,
            "data_quality": data_quality,
            "rationale": "Mock provider mirrors deterministic confidence.",
            "validation_warnings": [],
        },
        "context_note": "",
    }


def _severity_from_raw(findings: list[dict], status: str | None) -> str:
    if findings:
        top = max((SEVERITY_RANK.get(f.get("severity"), 1) for f in findings), default=1)
        return {rank: level for level, rank in SEVERITY_RANK.items()}[top]
    if status == "critical":
        return "critical"
    if status == "attention":
        return "warning"
    return "info"


def _confidence_from_raw(value: Any) -> float:
    if isinstance(value, (int, float)):
        return round(max(0.05, min(0.95, float(value))), 3)
    return 0.5


def _likelihood_from_severity(severity: str | None) -> str:
    return {"critical": "high", "warning": "medium", "info": "low"}.get(severity or "", "medium")
