"""Deterministic assessments derived from the Vehicle Health Context (Phase 4).

Severity and confidence are computed from the Phase 3 engine output only and
mirrored in the structured response. The LLM enriches and explains these
values; it can never override them.
"""

from __future__ import annotations

from app.intelligence.models import HealthContext, Severity

SEVERITY_RANK: dict[str, int] = {"critical": 3, "warning": 2, "info": 1}
_REVERSE_RANK = {rank: level for level, rank in SEVERITY_RANK.items()}


def derive_severity(context: HealthContext | None) -> Severity:
    """Highest-severity finding wins; otherwise fall back to overall status."""
    if context is None:
        return "info"
    if context.findings:
        top = max(
            (SEVERITY_RANK[item.severity] for item in context.findings),
            default=SEVERITY_RANK["info"],
        )
        return _REVERSE_RANK[top]
    if context.health_status == "critical":
        return "critical"
    if context.health_status == "attention":
        return "warning"
    return "info"


def derive_confidence(context: HealthContext | None) -> float:
    """Blend engine confidence with window data coverage, bounded to [0.05, 0.95]."""
    if context is None:
        return 0.0
    score_confidence = context.confidence if context.confidence is not None else 0.5
    coverage = context.data_quality.coverage_ratio
    coverage = coverage if coverage is not None else 0.0
    data_factor = 0.5 + 0.5 * max(0.0, min(1.0, coverage))
    blended = score_confidence * 0.6 + data_factor * 0.4
    return round(max(0.05, min(0.95, blended)), 3)


def derive_score_quality(context: HealthContext | None) -> str:
    """Label for the quality of the deterministic health assessment."""
    if context is None or context.confidence is None:
        return "low"
    return _quality_label(context.confidence)


def derive_data_quality(context: HealthContext | None) -> str:
    """Label for the telemetry coverage observed in the analysis window."""
    if context is None:
        return "low"
    coverage = context.data_quality.coverage_ratio
    if coverage is None:
        return "low"
    return _quality_label(coverage)


def _quality_label(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"
