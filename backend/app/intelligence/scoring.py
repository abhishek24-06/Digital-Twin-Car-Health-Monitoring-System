"""Deterministic health scoring, status classification and confidence.

Health score model (documented):
    - start at 100
    - penalty per finding by severity: info=0, warning=10, critical=30
    - penalties are accumulated per category; each category is capped at
      40 points so a single category cannot dominate the score
    - score = clamp(100 - total_penalty, 0, 100)

Health status thresholds (documented):
    - insufficient data                                   -> "unknown"
    - score >= 80                                         -> "healthy"
    - 60 <= score < 80                                    -> "attention"
    - score < 60                                          -> "critical"

The score is an internal heuristic indicator of configured-rule activity in
the analysed window. It is NOT a manufacturer rating, safety certification,
mechanical diagnosis or probability of failure.

Confidence measures confidence *in this telemetry-based assessment* (data
volume, coverage, duration and completeness), NOT the probability that the
vehicle is healthy.
"""

from __future__ import annotations

from app.intelligence.models import (
    SUPPORTED_METRICS,
    AnalysisWindow,
    DataQuality,
    Finding,
    HealthStatus,
    MetricStatistics,
    PenaltyComponent,
    ScoreDetails,
)

#: Penalty per finding by severity.
FINDING_PENALTIES: dict[str, float] = {"info": 0.0, "warning": 10.0, "critical": 30.0}

#: Maximum penalty a single category may contribute to the score.
CATEGORY_PENALTY_CAP = 40.0

#: Status thresholds (score).
STATUS_HEALTHY_MIN = 80.0
STATUS_ATTENTION_MIN = 60.0


def health_status_from_score(score: float | None) -> HealthStatus:
    if score is None:
        return "unknown"
    if score >= STATUS_HEALTHY_MIN:
        return "healthy"
    if score >= STATUS_ATTENTION_MIN:
        return "attention"
    return "critical"


def score_findings(findings: list[Finding]) -> ScoreDetails:
    """Convert findings into a transparent health score and status."""
    per_category: dict[str, dict] = {}
    components: list[PenaltyComponent] = []

    for finding in findings:
        severity = finding.severity
        penalty = FINDING_PENALTIES.get(severity, 0.0)
        entry = per_category.setdefault(
            finding.category, {"penalty": 0.0, "counts": {}, "capped": False}
        )
        entry["penalty"] += penalty
        entry["counts"][severity] = entry["counts"].get(severity, 0) + 1

    total_penalty = 0.0
    for category, entry in sorted(per_category.items()):
        capped = entry["penalty"] > CATEGORY_PENALTY_CAP
        applied = min(entry["penalty"], CATEGORY_PENALTY_CAP)
        total_penalty += applied
        # Prefer the highest severity present for reporting.
        severity = (
            "critical"
            if entry["counts"].get("critical")
            else ("warning" if entry["counts"].get("warning") else "info")
        )
        components.append(
            PenaltyComponent(
                category=category,
                severity=severity,
                finding_count=sum(entry["counts"].values()),
                penalty=round(applied, 2),
                capped=capped,
            )
        )

    score = round(100.0 - total_penalty, 2) if findings else 100.0
    score = max(0.0, min(100.0, score))
    status = health_status_from_score(score)
    return ScoreDetails(
        score=score,
        status=status,
        total_penalty=round(total_penalty, 2),
        components=components,
    )


def compute_confidence(
    data_quality: DataQuality,
    statistics: dict[str, MetricStatistics],
    window: AnalysisWindow,
) -> float:
    """Confidence in the telemetry-based assessment (0-1). See module docstring."""
    expected = max(data_quality.expected_sample_count, 0)
    sample_sufficiency = min(1.0, data_quality.sample_count / expected) if expected > 0 else 0.0
    duration_ratio = (
        min(1.0, data_quality.duration_seconds / window.duration_seconds)
        if data_quality.duration_seconds is not None and window.duration_seconds > 0
        else 0.0
    )
    coverage = data_quality.coverage_ratio or 0.0
    completeness = max(0.0, min(1.0, len(statistics) / len(SUPPORTED_METRICS)))

    confidence = 0.10 + 0.90 * (
        0.30 * coverage + 0.25 * duration_ratio + 0.25 * sample_sufficiency + 0.20 * completeness
    )
    return round(max(0.0, min(1.0, confidence)), 4)


def insufficient_score(notes: list[str] | None = None) -> ScoreDetails:
    """ScoreDetails for an assessment that could not be produced."""
    return ScoreDetails(
        score=None,
        status="unknown",
        notes=list(notes or []),
    )
