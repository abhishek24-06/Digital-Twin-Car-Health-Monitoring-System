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
#: 1.2 added ``analysis_scope`` (current-session vs historical window).
CONTEXT_SCHEMA_VERSION = "1.2"

#: Version of the deterministic rule/analysis engine.
RULE_ENGINE_VERSION = "1.0"

TrendDirection = Literal["increasing", "decreasing", "stable", "insufficient_data"]
TrendStrength = Literal["none", "weak", "moderate", "strong"]
Severity = Literal["info", "warning", "critical"]
#: The definitive health classification. ``no_data`` (no telemetry) and
#: ``limited_data`` (fewer samples than the hard minimum) are data-state
#: labels: a limited-data assessment is *provisional* and the actual rating
#: (healthy/attention/critical) is exposed via ``ScoreDetails.status`` and
#: ``HealthContext.provisional_rating``.
HealthStatus = Literal["healthy", "attention", "critical", "unknown", "no_data", "limited_data"]
#: Amount of telemetry the health assessment is based on.
DataSufficiency = Literal["no_data", "limited_data", "sufficient_data"]
BaselineStatus = Literal["within", "elevated", "depressed", "insufficient_history"]
#: Scope of an assessment's evidence: a run-scoped *current session* or a
#: bounded *historical window* that may span several runs and legacy rows.
#: Historical assessments never count as current health.
AnalysisScope = Literal["current_session", "historical_window"]

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


#: Ratings that reflect the vehicle's condition rather than its data state.
RATING_STATUSES: tuple[str, ...] = ("healthy", "attention", "critical")


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
    #: Amount of telemetry this assessment is based on (Phase 10).
    data_sufficiency: DataSufficiency = "sufficient_data"
    #: True when the assessment is provisional (limited data, low confidence).
    provisional: bool = False
    #: The best available rating while ``health_status`` is a data-state label
    #: (e.g. ``limited_data`` with a ``critical`` provisional rating).
    provisional_rating: HealthStatus | None = None
    #: Simulator-run provenance of the evidence this assessment is based on.
    #: ``None`` for a window/historical analysis or legacy unbounded evidence.
    simulation_run_id: UUID | None = None
    #: Live current-session sufficiency evaluation (present only for live
    #: analysis): why the assessment is provisional/met and what is required.
    live_sufficiency: LiveSufficiencyState | None = None
    #: Scope of the assessment evidence. ``current_session`` only for a
    #: run-scoped live evaluation; every window analysis (and any legacy
    #: context that predates this field) is ``historical_window``.
    analysis_scope: AnalysisScope = "historical_window"


class LiveSufficiencyPolicy(BaseModel):
    """Configurable gate a live current-session assessment must clear before it
    can be treated as definitive (Phase 4.2).

    All bounds are per active simulator run; historical samples never count.
    """

    minimum_samples: int = 30
    minimum_duration_seconds: float = 30.0
    minimum_coverage: float = 0.5
    max_sample_age_seconds: float = 15.0


class LiveSufficiencyState(BaseModel):
    """Outcome of evaluating a live run against :class:`LiveSufficiencyPolicy`.

    ``policy_met`` is True only when every bound holds. The individual numbers
    are echoed so the UI can show "samples 12/30, 20s/30s observed, 40% coverage,
    newest sample 5s old" instead of a bare yes/no.
    """

    policy_met: bool
    sample_count: int = 0
    required_sample_count: int = 0
    observation_duration_seconds: float | None = None
    required_duration_seconds: float = 0.0
    coverage_ratio: float | None = None
    required_coverage: float = 0.0
    latest_sample_age_seconds: float | None = None
    max_sample_age_seconds: float = 0.0
    reasons: list[str] = Field(default_factory=list)
