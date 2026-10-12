"""Vehicle Health Context assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.intelligence.models import (
    CONTEXT_SCHEMA_VERSION,
    RULE_ENGINE_VERSION,
    AnalysisWindow,
    BaselineInsight,
    DataQuality,
    Finding,
    HealthContext,
    LiveSufficiencyState,
    MetricStatistics,
    ScoreDetails,
    TrendInsight,
)


def build_context(
    *,
    vehicle_id: UUID,
    generated_at: datetime,
    analysis_duration_ms: float | None,
    analysis_window: AnalysisWindow,
    data_quality: DataQuality,
    statistics: dict[str, MetricStatistics],
    trends: list[TrendInsight],
    baselines: list[BaselineInsight],
    findings: list[Finding],
    score_details: ScoreDetails,
    confidence: float | None,
    data_sufficiency: str = "sufficient_data",
    provisional: bool = False,
    provisional_rating: str | None = None,
    simulation_run_id: UUID | None = None,
    live_sufficiency: LiveSufficiencyState | None = None,
) -> HealthContext:
    """Assemble the typed, versioned, serializable health context."""
    if data_sufficiency == "no_data":
        status = "no_data"
    elif data_sufficiency == "limited_data":
        status = "limited_data"
    else:
        status = score_details.status
    return HealthContext(
        vehicle_id=vehicle_id,
        context_schema_version=CONTEXT_SCHEMA_VERSION,
        rule_engine_version=RULE_ENGINE_VERSION,
        generated_at=generated_at,
        analysis_duration_ms=analysis_duration_ms,
        analysis_window=analysis_window,
        data_quality=data_quality,
        statistics=statistics,
        trends=trends,
        baselines=baselines,
        findings=findings,
        health_score=score_details.score,
        health_status=status,
        confidence=confidence,
        score_details=score_details,
        data_sufficiency=data_sufficiency,
        provisional=provisional,
        provisional_rating=provisional_rating,
        simulation_run_id=simulation_run_id,
        live_sufficiency=live_sufficiency,
        # A live current-session evaluation always carries a sufficiency
        # outcome; every windowed/historical analysis does not. This is the
        # single place scope is decided, so stored context is unambiguous.
        analysis_scope=(
            "current_session" if live_sufficiency is not None else "historical_window"
        ),
    )


def now_utc() -> datetime:
    return datetime.now(UTC)
