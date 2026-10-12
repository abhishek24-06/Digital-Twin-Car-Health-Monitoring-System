"""Read-only historical analytics over persisted telemetry.

Everything here is bounded aggregation over an explicit, validated,
UTC-aware window -- the same immutable records the health pipeline uses.
Nothing is ever rewritten, and the active live session is not privileged over
finished runs: run segment boundaries come from the persisted
``simulation_run_id`` column.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.intelligence.models import SUPPORTED_METRICS, TelemetryPoint
from app.intelligence.trends import analyze_trends
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas.historical_analytics import (
    GapSummary,
    HistoricalAnalyticsResponse,
    MetricSummary,
    RunSegment,
    SampleBucket,
    TrendSummaryItem,
)
from app.services.vehicle_access import ensure_vehicle_access

if TYPE_CHECKING:
    from app.models.user import User

logger = logging.getLogger(__name__)

RANGE_PRESETS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def _window_limit(window_minutes: float, expected_interval_seconds: float) -> int:
    seconds = max(window_minutes, 0.0) * 60.0
    expected = seconds / max(expected_interval_seconds, 1e-9)
    return int(expected) * 2 + 100


def _bucket_size_seconds(duration_seconds: float) -> int:
    if duration_seconds <= 2 * 3600:  # <= 2h
        return 600
    if duration_seconds <= 48 * 3600:  # <= 48h
        return 3600
    return 86400


def _timestamp_bucket(
    value: datetime, bucket_seconds: int, zone: ZoneInfo
) -> datetime:
    """Floor ``value`` to a bucket boundary.

    Daily buckets align to the requested timezone's local midnight; shorter
    buckets align uniformly to UTC epoch boundaries (labels are still rendered
    in the requested zone).
    """
    if bucket_seconds == 86400:
        local = value.astimezone(zone)
        return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    epoch_floor = math.floor(value.timestamp() / bucket_seconds) * bucket_seconds
    return datetime.fromtimestamp(epoch_floor, tz=UTC)


class HistoricalAnalyticsService:
    """Aggregate persisted telemetry within a validated historical window."""

    def __init__(
        self,
        session,
        vehicle_repository,
        telemetry_repository: TelemetryRepository,
        health_snapshot_repository,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._vehicle_repository = vehicle_repository
        self._telemetry_repository = telemetry_repository
        self._health_snapshot_repository = health_snapshot_repository
        self._settings = settings or get_settings()

    async def get_for_user(
        self,
        vehicle_id: UUID,
        user: User,
        *,
        range_preset: str,
        timezone: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> HistoricalAnalyticsResponse:
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)

        end = end_time if range_preset == "custom" else datetime.now(UTC)
        if range_preset == "custom":
            assert start_time is not None and end_time is not None  # validated upstream
            start = start_time
        else:
            start = end - RANGE_PRESETS[range_preset]

        return await self._aggregate(
            vehicle_id,
            range_preset=range_preset,
            timezone=timezone,
            start=start.astimezone(UTC),
            end=end.astimezone(UTC),
        )

    async def _aggregate(
        self,
        vehicle_id: UUID,
        *,
        range_preset: str,
        timezone: str,
        start: datetime,
        end: datetime,
    ) -> HistoricalAnalyticsResponse:
        if await self._vehicle_repository.get_by_id(vehicle_id) is None:
            raise NotFoundError("Vehicle")

        interval = self._settings.health_expected_interval_seconds
        window_minutes = max(0.0, (end - start).total_seconds() / 60.0)
        limit = _window_limit(window_minutes, interval)

        records = await self._telemetry_repository.get_recent_telemetry(
            vehicle_id, start_time=start, end_time=end, limit=limit
        )
        points = [
            TelemetryPoint(
                timestamp=r.timestamp,
                values={m: getattr(r, m, None) for m in SUPPORTED_METRICS},
            )
            for r in records
        ]

        metric_rows: list[MetricSummary] = []
        for metric in SUPPORTED_METRICS:
            values = [
                p.values.get(metric)
                for p in points
                if p.values.get(metric) is not None
            ]
            row = MetricSummary(metric=metric, valid_samples=len(values))
            if values:
                row.min_value = min(values)
                row.max_value = max(values)
                row.mean_value = round(statistics.fmean(values), 4)
                row.median_value = round(statistics.median(values), 4)
                row.stddev_value = (
                    round(statistics.stdev(values), 4) if len(values) > 1 else 0.0
                )
                row.delta_value = round(values[-1] - values[0], 4)
                stamped = [p for p in points if p.values.get(metric) is not None]
                if stamped:
                    row.first_timestamp = stamped[0].timestamp
                    row.last_timestamp = stamped[-1].timestamp
            metric_rows.append(row)

        trends = [
            TrendSummaryItem(
                metric=t.metric,
                direction=t.direction,
                strength=t.strength,
                slope=t.slope,
            )
            for t in analyze_trends(points, SUPPORTED_METRICS)
        ]

        # Gaps: any inter-sample jump beyond 3x the expected interval.
        max_gap: float | None = None
        gap_count = 0
        tolerance = interval * 3.0
        timestamps = [r.timestamp for r in records]
        for older, newer in zip(timestamps, timestamps[1:], strict=False):
            gap = (newer - older).total_seconds()
            if gap > tolerance:
                gap_count += 1
                max_gap = gap if max_gap is None else max(max_gap, gap)

        # Time-bucketed sample counts for charts (bounded by loaded rows).
        zone = ZoneInfo(timezone)
        bucket_seconds = _bucket_size_seconds((end - start).total_seconds())
        counts: Counter[datetime] = Counter()
        for ts in timestamps:
            counts[_timestamp_bucket(ts, bucket_seconds, zone)] += 1
        buckets = [
            SampleBucket(
                bucket_start=bk,
                bucket_end=bk + timedelta(seconds=bucket_seconds),
                sample_count=cnt,
            )
            for bk, cnt in sorted(counts.items())
        ]

        # Run boundary segments from persisted provenance.
        segments_raw = await self._telemetry_repository.get_run_segments(
            vehicle_id, start_time=start, end_time=end
        )
        run_segments = [
            RunSegment(
                run_id=run_id,
                samples=count,
                first_timestamp=first_ts,
                last_timestamp=last_ts,
                is_legacy=run_id is None,
            )
            for run_id, count, first_ts, last_ts in segments_raw
        ]

        snapshots, snapshot_total = await self._health_snapshot_repository.list_by_vehicle(
            vehicle_id, page=1, page_size=200, start_time=start, end_time=end
        )

        return HistoricalAnalyticsResponse(
            vehicle_id=vehicle_id,
            range=range_preset,
            window_start=start,
            window_end=end,
            duration_seconds=max(0.0, (end - start).total_seconds()),
            timezone=timezone,
            total_samples=len(records),
            earliest_sample_at=timestamps[0] if timestamps else None,
            latest_sample_at=timestamps[-1] if timestamps else None,
            metrics=metric_rows,
            trends=trends,
            buckets=buckets,
            gaps=GapSummary(
                max_gap_seconds=max_gap,
                gap_count=gap_count,
                expected_interval_seconds=interval,
            ),
            run_segments=run_segments,
            snapshot_count=snapshot_total,
            snapshots_present=snapshot_total > 0,
        )
