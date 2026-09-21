"""Typed domain models for the Phase 3 vehicle health intelligence layer.

These Pydantic v2 models define the deterministic, structured Vehicle Health
Context consumed by the REST API and (in Phase 4) by the agent layer. Every
model is JSON-serialisable via ``model_dump(mode="json")``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

#: Version of the Vehicle Health Context schema. Bump when the shape changes.
CONTEXT_SCHEMA_VERSION = "1.0"

#: Version of the deterministic rule/analysis engine.
RULE_ENGINE_VERSION = "1.0"

TrendDirection = Literal["increasing", "decreasing", "stable", "insufficient_data"]
TrendStrength = Literal["none", "weak", "moderate", "strong"]
Severity = Literal["info", "warning", "critical"]
HealthStatus = Literal["healthy", "attention", "critical", "unknown"]
BaselineStatus = Literal["within", "elevated", "depressed", "insufficient_history"]

#: Physical units for every supported telemetry metric.
METRIC_UNITS: dict[str, str] = {
    "rpm": "RPM",
    "speed": "km/h",
    "engine_load": "%",
    "coolant_temperature": "C",
    "oil_temperature": "C",
    "battery_voltage": "V",
    "fuel_level": "%",
    "intake_air_temperature": "C",
    "throttle_position": "%",
    "engine_runtime": "s",
    "odometer": "km",
}

SUPPORTED_METRICS: tuple[str, ...] = tuple(METRIC_UNITS.keys())


class TelemetryPoint(BaseModel):
    """One telemetry sample decoupled from its transport (MQTT/REST/fixture)."""

    timestamp: datetime
    values: dict[str, float | None]


class AnalysisWindow(BaseModel):
    """The historical telemetry window an analysis was performed over."""

    start: datetime
    end: datetime
    window_minutes: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


class MetricStatistics(BaseModel):
    """Statistical summary of a single numeric telemetry metric."""

    metric: str
    unit: str
    count: int
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    std_dev: float | None = None
    first: float | None = None
    last: float | None = None
    range: float | None = None
    percentile_25: float | None = None
    percentile_75: float | None = None
    coefficient_of_variation: float | None = None


class DataQuality(BaseModel):
    """Data-quality characteristics of the analysed telemetry window.

    Missing samples are a data-quality concern, not a vehicle fault.
    """

    sample_count: int
    expected_sample_count: int
    coverage_ratio: float | None = None
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    duration_seconds: float | None = None
    missing_sample_estimate: int = 0
    max_gap_seconds: float | None = None
    timestamp_order_valid: bool = True


class TrendInsight(BaseModel):
    """Detected direction of change for a single metric over the window."""

    metric: str
    unit: str
    direction: TrendDirection
    slope: float | None = None
    normalized_slope: float | None = None
    strength: TrendStrength | None = None
    sample_count: int


class BaselineInsight(BaseModel):
    """Comparison of current telemetry against the vehicle's historical baseline."""

    metric: str
    unit: str
    center: float | None = None
    spread: float | None = None
    sample_count: int
    current_value: float | None = None
    normalized_deviation: float | None = None
    status: BaselineStatus
    note: str | None = None


class Finding(BaseModel):
    """A deterministic, factual observation produced by the rule engine.

    Findings describe telemetry-derived evidence only. They never state a
    mechanical diagnosis (e.g. "water pump failed").
    """

    rule_id: str
    severity: Severity
    category: str
    metric: str | None = None
    observed_value: float | None = None
    threshold: float | None = None
    unit: str | None = None
    message: str
    confidence: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None


class PenaltyComponent(BaseModel):
    """Per-category penalty applied towards the health score."""

    category: str
    severity: Severity
    finding_count: int
    penalty: float
    capped: bool = False


class ScoreDetails(BaseModel):
    """Transparent breakdown of how the health score was computed."""

    score: float | None
    status: HealthStatus
    starting_score: float = 100.0
    total_penalty: float = 0.0
    components: list[PenaltyComponent] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class HealthContext(BaseModel):
    """The complete, serialisable Vehicle Health Context produced by analysis."""

    vehicle_id: UUID
    context_schema_version: str = CONTEXT_SCHEMA_VERSION
    rule_engine_version: str = RULE_ENGINE_VERSION
    generated_at: datetime
    analysis_duration_ms: float | None = None
    analysis_window: AnalysisWindow
    data_quality: DataQuality
    statistics: dict[str, MetricStatistics]
    trends: list[TrendInsight]
    baselines: list[BaselineInsight]
    findings: list[Finding]
    health_score: float | None
    health_status: HealthStatus
    confidence: float | None
    score_details: ScoreDetails
