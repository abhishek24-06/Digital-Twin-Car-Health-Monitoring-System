from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.intelligence.engine import HealthAnalysisEngine
from app.intelligence.models import (
    SUPPORTED_METRICS,
    AnalysisWindow,
    HealthContext,
    LiveSufficiencyPolicy,
    TelemetryPoint,
)
from app.models.health_snapshot import HealthSnapshot
from app.models.user import User
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.vehicle_access import ensure_vehicle_access

logger = logging.getLogger(__name__)


def _window_limit(window_minutes: float, expected_interval_seconds: float) -> int:
    """A bounded worst-case row estimate for an analysis/baseline window."""
    seconds = max(window_minutes, 0.0) * 60.0
    expected = seconds / max(expected_interval_seconds, 1e-9)
    return int(expected) * 2 + 100


def _to_points(records) -> list[TelemetryPoint]:
    return [
        TelemetryPoint(
            timestamp=record.timestamp,
            values={field: getattr(record, field, None) for field in SUPPORTED_METRICS},
        )
        for record in records
    ]


class VehicleHealthService:
    """Orchestrates health snapshot generation and retrieval.

    Service -> Analysis Engine -> Repository. The analysis engine is
    transport-agnostic; only this service translates ORM records into typed
    telemetry points.
    """

    def __init__(
        self,
        session: AsyncSession,
        vehicle_repository: VehicleRepository,
        telemetry_repository: TelemetryRepository,
        health_repository: HealthSnapshotRepository,
        settings: Settings | None = None,
        engine: HealthAnalysisEngine | None = None,
    ) -> None:
        self._session = session
        self._vehicle_repository = vehicle_repository
        self._telemetry_repository = telemetry_repository
        self._health_repository = health_repository
        self._settings = settings or get_settings()
        self._engine = engine or HealthAnalysisEngine()

    async def analyze_vehicle_for_user(
        self, vehicle_id: UUID, user: User, window_minutes: float | None = None
    ) -> HealthSnapshot:
        """User-scoped analyze: ownership is enforced below the router."""
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self.analyze_vehicle(vehicle_id, window_minutes=window_minutes)

    async def get_latest_for_user(self, vehicle_id: UUID, user: User) -> HealthSnapshot | None:
        """User-scoped latest snapshot: ownership is enforced below the router."""
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self.get_latest(vehicle_id)

    async def list_history_for_user(
        self,
        vehicle_id: UUID,
        user: User,
        *,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[list[HealthSnapshot], int]:
        """User-scoped history: ownership is enforced below the router."""
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self.list_history(
            vehicle_id,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
        )

    async def analyze_vehicle(
        self, vehicle_id: UUID, window_minutes: float | None = None
    ) -> HealthSnapshot:
        """Analyze a vehicle's telemetry window, persist a snapshot, return it."""
        if await self._vehicle_repository.get_by_id(vehicle_id) is None:
            raise NotFoundError("Vehicle")
        if window_minutes is not None and window_minutes <= 0:
            raise ValueError("window_minutes must be greater than zero")
        window_minutes = window_minutes or float(self._settings.health_analysis_window_minutes)

        interval = self._settings.health_expected_interval_seconds
        window_end = datetime.now(UTC)
        window_start = window_end - timedelta(minutes=window_minutes)
        window = AnalysisWindow(start=window_start, end=window_end, window_minutes=window_minutes)

        limit = _window_limit(window_minutes, interval)
        records = await self._telemetry_repository.get_recent_telemetry(
            vehicle_id, start_time=window_start, end_time=window_end, limit=limit
        )
        samples = _to_points(records)

        history: list[TelemetryPoint] = []
        baseline_minutes = float(self._settings.health_baseline_window_minutes)
        if baseline_minutes > 0:
            baseline_limit = _window_limit(baseline_minutes, interval)
            history_records = await self._telemetry_repository.get_recent_telemetry(
                vehicle_id,
                start_time=window_start - timedelta(minutes=baseline_minutes),
                end_time=window_start,
                limit=baseline_limit,
            )
            history = _to_points(history_records)

        context = self._engine.analyze(
            vehicle_id=vehicle_id,
            window=window,
            samples=samples,
            history=history,
            minimum_samples=self._settings.health_minimum_samples,
            expected_interval_seconds=interval,
            baseline_minimum_samples=self._settings.health_baseline_minimum_samples,
        )

        snapshot = self._snapshot_from_context(vehicle_id, context)
        created = await self._health_repository.create(snapshot)
        await self._session.commit()
        logger.info(
            "health snapshot persisted: vehicle_id=%s snapshot_id=%s status=%s score=%s",
            vehicle_id,
            created.id,
            created.health_status,
            created.health_score,
        )
        return created

    async def analyze_live_vehicle_for_user(
        self, vehicle_id: UUID, run_id: UUID, user: User, *, persist: bool = True
    ) -> HealthSnapshot:
        """User-scoped live analysis: ownership is enforced below the router."""
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self.analyze_live_vehicle(vehicle_id, run_id, persist=persist)

    async def analyze_live_vehicle(
        self,
        vehicle_id: UUID,
        run_id: UUID,
        *,
        generated_at: datetime | None = None,
        persist: bool = True,
    ) -> HealthSnapshot:
        """Analyse the *current session* of one vehicle (active run only).

        Used by the live-health endpoint and the background monitor. Only
        telemetry rows carrying the exact active ``run_id`` are counted as
        current-run evidence; historical samples are loaded through a separate
        baseline query and are never fused into the current-run statistics.

        A fresh run (or none) therefore yields ``no_data``/``limited_data``
        (provisional / collecting) instead of a stale window verdict, and the
        assessed window shrinks to the run's own observation span so coverage
        and duration reflect the current session, not a 15-minute rolling
        sweep across sessions.

        ``persist=False`` evaluates without writing a snapshot: a read endpoint
        (``GET /health/live``) must not create records as a side-effect, or a
        poll loop silently fills the snapshot history. The background monitor
        keeps the default (``persist=True``) so evidence is still captured.
        """
        if await self._vehicle_repository.get_by_id(vehicle_id) is None:
            raise NotFoundError("Vehicle")

        now = generated_at or datetime.now(UTC)
        window_minutes = float(self._settings.health_analysis_window_minutes)
        outer_start = now - timedelta(minutes=window_minutes)
        interval = self._settings.health_expected_interval_seconds

        # Current-session evidence: only the active run's rows, within the
        # analysis window, bounded worst case.
        limit = _window_limit(window_minutes, interval)
        records = await self._telemetry_repository.get_recent_telemetry(
            vehicle_id,
            start_time=outer_start,
            end_time=now,
            limit=limit,
            run_id=run_id,
        )
        samples = _to_points(records)

        # Observation window = the run's span inside the analysis window. A
        # run with no persisted samples yet sees a zero-length window (no data).
        if records:
            session_start = max(outer_start, records[0].timestamp)
        else:
            session_start = now
        session_minutes = max(0.0, (now - session_start).total_seconds() / 60.0)
        window = AnalysisWindow(
            start=session_start, end=now, window_minutes=session_minutes
        )

        # Historical baseline: separate query, ending at the analysis window
        # start, and excluding this run so a current session never biases its
        # own baseline. Never counted as current-run observations.
        history: list[TelemetryPoint] = []
        baseline_minutes = float(self._settings.health_baseline_window_minutes)
        if baseline_minutes > 0:
            baseline_limit = _window_limit(baseline_minutes, interval)
            history_records = await self._telemetry_repository.get_recent_telemetry(
                vehicle_id,
                start_time=outer_start - timedelta(minutes=baseline_minutes),
                end_time=outer_start,
                limit=baseline_limit,
                exclude_run_id=run_id,
            )
            history = _to_points(history_records)

        policy = LiveSufficiencyPolicy(
            minimum_samples=self._settings.live_health_minimum_samples,
            minimum_duration_seconds=self._settings.live_health_minimum_duration_seconds,
            minimum_coverage=self._settings.live_health_minimum_coverage,
            max_sample_age_seconds=self._settings.live_health_max_sample_age_seconds,
        )
        context = self._engine.analyze(
            vehicle_id=vehicle_id,
            window=window,
            samples=samples,
            history=history,
            minimum_samples=max(
                self._settings.health_minimum_samples, policy.minimum_samples
            ),
            expected_interval_seconds=interval,
            baseline_minimum_samples=self._settings.health_baseline_minimum_samples,
            generated_at=now,
            simulation_run_id=run_id,
            sufficiency_policy=policy,
        )

        snapshot = self._snapshot_from_context(vehicle_id, context)
        if not persist:
            logger.debug(
                "live health evaluated without persisting: vehicle_id=%s run_id=%s "
                "status=%s provisional=%s",
                vehicle_id,
                run_id,
                snapshot.health_status,
                context.provisional,
            )
            return snapshot
        created = await self._health_repository.create(snapshot)
        await self._session.commit()
        logger.info(
            "live health snapshot persisted: vehicle_id=%s run_id=%s status=%s provisional=%s",
            vehicle_id,
            run_id,
            created.health_status,
            context.provisional,
        )
        return created

    async def latest_run_evidence(
        self,
        vehicle_id: UUID,
        run_id: UUID,
        *,
        after: datetime | None = None,
    ) -> tuple[datetime | None, datetime | None]:
        """(newest source timestamp, newest persisted-at) for one active run.

        Splits measurement chronology from ingestion time so the live view can
        report both honestly. Returns ``(None, None)`` when the run has no
        persisted rows yet.
        """
        record = await self._telemetry_repository.get_latest_run_record(
            vehicle_id, run_id, after=after
        )
        if record is None:
            return None, None
        return record.timestamp, record.created_at

    async def get_latest(self, vehicle_id: UUID) -> HealthSnapshot | None:
        if await self._vehicle_repository.get_by_id(vehicle_id) is None:
            raise NotFoundError("Vehicle")
        return await self._health_repository.get_latest_by_vehicle(vehicle_id)

    async def list_history(
        self,
        vehicle_id: UUID,
        *,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[list[HealthSnapshot], int]:
        if await self._vehicle_repository.get_by_id(vehicle_id) is None:
            raise NotFoundError("Vehicle")
        return await self._health_repository.list_by_vehicle(
            vehicle_id,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
        )

    @staticmethod
    def _snapshot_from_context(vehicle_id: UUID, context: HealthContext) -> HealthSnapshot:
        return HealthSnapshot(
            vehicle_id=vehicle_id,
            generated_at=context.generated_at,
            window_start=context.analysis_window.start,
            window_end=context.analysis_window.end,
            sample_count=context.data_quality.sample_count,
            health_score=context.health_score,
            health_status=context.health_status,
            confidence=context.confidence,
            context_schema_version=context.context_schema_version,
            context_json=context.model_dump(mode="json"),
        )
