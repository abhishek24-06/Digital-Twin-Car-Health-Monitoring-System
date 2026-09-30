from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.intelligence.engine import HealthAnalysisEngine
from app.intelligence.models import SUPPORTED_METRICS, AnalysisWindow, HealthContext, TelemetryPoint
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
