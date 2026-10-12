"""API response schemas for the vehicle health endpoints.

The full Vehicle Health Context is validated through the intelligence domain
models (single source of truth for the context schema).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.intelligence.models import (
    AnalysisScope,
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


class HealthContextResponse(BaseModel):
    """The complete serialized Vehicle Health Context returned by the API."""

    vehicle_id: UUID
    context_schema_version: str
    rule_engine_version: str
    generated_at: datetime
    analysis_duration_ms: float | None = None
    analysis_window: AnalysisWindow
    data_quality: DataQuality
    statistics: dict[str, MetricStatistics]
    trends: list[TrendInsight]
    baselines: list[BaselineInsight]
    findings: list[Finding]
    health_score: float | None = None
    health_status: str
    confidence: float | None = None
    score_details: ScoreDetails
    data_sufficiency: str = "sufficient_data"
    provisional: bool = False
    provisional_rating: str | None = None
    #: Simulator-run provenance of the assessment evidence (None for window /
    #: historical analysis or legacy evidence without a run identity).
    simulation_run_id: UUID | None = None
    #: Live sufficiency outcome (present only for live current-session analysis).
    live_sufficiency: LiveSufficiencyState | None = None
    #: Scope of the assessment evidence: a run-scoped current session or a
    #: bounded historical window (which may span runs and legacy rows).
    analysis_scope: AnalysisScope = "historical_window"

    @classmethod
    def from_context(cls, context: HealthContext) -> HealthContextResponse:
        return cls.model_validate(context.model_dump(mode="json"))


class HealthSnapshotItem(BaseModel):
    """Lightweight history entry exposing queryable top-level columns."""

    id: UUID
    vehicle_id: UUID
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    sample_count: int
    health_score: float | None = None
    health_status: str
    confidence: float | None = None
    context_schema_version: str

    model_config = ConfigDict(from_attributes=True)


LiveFreshnessState = Literal["no_session", "no_data", "collecting", "stale", "fresh"]


class LiveHealthStatusResponse(BaseModel):
    """Current-session health status for one vehicle.

    This is the honest live view: the assessment is only present when there is
    an active simulator run with sufficient fresh current-run evidence. A
    stopped vehicle, a collecting session, or a stale feed never reuses an old
    snapshot as if it were current.
    """

    vehicle_id: UUID
    #: Active simulator run identity (None when no run is active).
    run_id: UUID | None = None
    simulator_state: str
    live_state: LiveFreshnessState
    latest_source_timestamp: datetime | None = None
    latest_persisted_at: datetime | None = None
    sample_count: int = 0
    required_sample_count: int = 0
    observation_duration_seconds: float | None = None
    required_duration_seconds: float = 0.0
    coverage_ratio: float | None = None
    required_coverage: float = 0.0
    latest_sample_age_seconds: float | None = None
    max_sample_age_seconds: float = 0.0
    sample_timestamp_order_valid: bool = True
    insufficiency_reasons: list[str] = Field(default_factory=list)
    #: The current-session assessment (None while collecting / no session).
    assessment: HealthContextResponse | None = None
    #: When the last live evaluation produced a snapshot (None if never).
    last_evaluated_at: datetime | None = None
    #: Human-readable context for the state (e.g. simulator reason, collecting
    #: explanation, stale-feed warning). Never fabricates a health claim.
    message: str | None = None
