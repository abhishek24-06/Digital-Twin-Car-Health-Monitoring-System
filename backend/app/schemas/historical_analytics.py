"""Wire schemas for historical analytics.

Strictly read-only analytics over persisted telemetry: bounded aggregation,
per-metric statistics, deterministic trend summary, health-snapshot history,
run-boundary segments and time-bucketed sample counts. Timestamps are always
UTC-aware; naive input is rejected.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

HistoricalRangePreset = Literal["1h", "24h", "7d", "30d", "90d", "custom"]

#: Max window width accepted for a custom range (bounds aggregation).
MAX_CUSTOM_RANGE_DAYS = 180


class HistoricalAnalyticsParams(BaseModel):
    """Query parameters for the historical analytics endpoint.

    ``range`` chooses a preset window anchored at request time; ``custom``
    requires explicit, timezone-aware ``start_time``/``end_time`` (reversed
    ranges are rejected). ``timezone`` is an IANA zone name used for display
    bucketing labels; it never alters the stored UTC timestamps.
    """

    range: HistoricalRangePreset = "24h"
    timezone: str = "UTC"
    start_time: datetime | None = None
    end_time: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:  # pragma: no cover - trivial passthrough
            raise ValueError(f"Unknown IANA timezone {value!r}") from exc
        return value

    @field_validator("start_time", "end_time")
    @classmethod
    def _validate_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("start_time/end_time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_range(self) -> HistoricalAnalyticsParams:
        if self.range == "custom":
            if self.start_time is None or self.end_time is None:
                raise ValueError("custom range requires start_time and end_time")
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be after start_time")
            width_days = (self.end_time - self.start_time).total_seconds() / 86400.0
            if width_days > MAX_CUSTOM_RANGE_DAYS:
                raise ValueError(
                    f"custom range must not exceed {MAX_CUSTOM_RANGE_DAYS} days"
                )
        return self


class MetricSummary(BaseModel):
    """Aggregate statistics for one supported metric over the window."""

    metric: str
    valid_samples: int
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    median_value: float | None = None
    stddev_value: float | None = None
    delta_value: float | None = None
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None


class SampleBucket(BaseModel):
    """One time bucket of persisted samples (chart-ready)."""

    bucket_start: datetime
    bucket_end: datetime
    sample_count: int


class GapSummary(BaseModel):
    """Largest inter-sample gap and count of gaps beyond tolerance."""

    max_gap_seconds: float | None = None
    gap_count: int = 0
    expected_interval_seconds: float


class RunSegment(BaseModel):
    """One simulator-run boundary (or the legacy no-run segment)."""

    run_id: UUID | None = None
    samples: int
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    is_legacy: bool = False


class TrendSummaryItem(BaseModel):
    """Deterministic trend classification for one metric."""

    metric: str
    direction: str
    strength: str | None = None
    slope: float | None = None


class HistoricalAnalyticsResponse(BaseModel):
    """Complete read-only analytics payload over a validated historical window."""

    vehicle_id: UUID
    range: HistoricalRangePreset
    window_start: datetime
    window_end: datetime
    duration_seconds: float
    timezone: str
    total_samples: int
    earliest_sample_at: datetime | None = None
    latest_sample_at: datetime | None = None
    metrics: list[MetricSummary] = Field(default_factory=list)
    trends: list[TrendSummaryItem] = Field(default_factory=list)
    buckets: list[SampleBucket] = Field(default_factory=list)
    gaps: GapSummary
    run_segments: list[RunSegment] = Field(default_factory=list)
    snapshot_count: int = 0
    snapshots_present: bool = False
