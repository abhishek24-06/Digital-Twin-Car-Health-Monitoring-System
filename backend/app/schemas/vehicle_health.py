"""API response schemas for the vehicle health endpoints.

The full Vehicle Health Context is validated through the intelligence domain
models (single source of truth for the context schema).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.intelligence.models import (
    AnalysisWindow,
    BaselineInsight,
    DataQuality,
    Finding,
    HealthContext,
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
