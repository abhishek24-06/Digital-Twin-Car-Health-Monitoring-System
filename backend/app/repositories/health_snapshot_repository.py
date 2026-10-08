from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.health_snapshot import HealthSnapshot
from app.models.telemetry import TelemetryRecord


class HealthSnapshotRepository:
    """Data access for persisted vehicle health snapshots (persistence only)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, snapshot: HealthSnapshot) -> HealthSnapshot:
        self._session.add(snapshot)
        await self._session.flush()
        await self._session.refresh(snapshot)
        return snapshot

    async def get_by_id(self, snapshot_id: UUID) -> HealthSnapshot | None:
        statement = select(HealthSnapshot).where(HealthSnapshot.id == snapshot_id)
        return await self._session.scalar(statement)

    async def get_latest_by_vehicle(self, vehicle_id: UUID) -> HealthSnapshot | None:
        statement = (
            select(HealthSnapshot)
            .where(HealthSnapshot.vehicle_id == vehicle_id)
            .order_by(HealthSnapshot.generated_at.desc(), HealthSnapshot.id.desc())
            .limit(1)
        )
        return await self._session.scalar(statement)

    async def list_by_vehicle(
        self,
        vehicle_id: UUID,
        *,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[list[HealthSnapshot], int]:
        filters = [HealthSnapshot.vehicle_id == vehicle_id]
        if start_time is not None:
            filters.append(HealthSnapshot.generated_at >= start_time)
        if end_time is not None:
            filters.append(HealthSnapshot.generated_at <= end_time)

        total = await self._session.scalar(
            select(func.count()).select_from(HealthSnapshot).where(*filters)
        )

        statement = (
            select(HealthSnapshot)
            .where(*filters)
            .order_by(HealthSnapshot.generated_at.desc(), HealthSnapshot.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.scalars(statement)
        return list(result.all()), int(total or 0)

    async def list_vehicle_ids_with_newer_telemetry(
        self, *, older_than: datetime | None = None, limit: int | None = None
    ) -> list[UUID]:
        """Vehicles whose newest telemetry is newer than their newest snapshot.

        This is the work queue for background health evaluation: a vehicle is
        *due* when telemetry has arrived since the last time it was evaluated,
        or when it has telemetry but has never been evaluated at all. Vehicles
        with no telemetry are never due.

        ``older_than`` additionally suppresses vehicles whose latest snapshot is
        newer than the given instant, which is the per-vehicle throttle between
        evaluations. A vehicle that has never been evaluated has no snapshot and
        is therefore never suppressed.
        """
        last_telemetry = (
            select(
                TelemetryRecord.vehicle_id.label("vehicle_id"),
                func.max(TelemetryRecord.timestamp).label("last_telemetry_at"),
            )
            .group_by(TelemetryRecord.vehicle_id)
            .subquery()
        )
        last_snapshot = (
            select(
                HealthSnapshot.vehicle_id.label("vehicle_id"),
                func.max(HealthSnapshot.generated_at).label("last_snapshot_at"),
            )
            .group_by(HealthSnapshot.vehicle_id)
            .subquery()
        )

        due = or_(
            last_snapshot.c.last_snapshot_at.is_(None),
            last_telemetry.c.last_telemetry_at > last_snapshot.c.last_snapshot_at,
        )
        if older_than is not None:
            throttle = or_(
                last_snapshot.c.last_snapshot_at.is_(None),
                last_snapshot.c.last_snapshot_at < older_than,
            )
            due = and_(due, throttle)

        statement = (
            select(last_telemetry.c.vehicle_id)
            .join(
                last_snapshot,
                last_snapshot.c.vehicle_id == last_telemetry.c.vehicle_id,
                isouter=True,
            )
            .where(due)
            .order_by(last_telemetry.c.vehicle_id)
        )
        if limit is not None:
            statement = statement.limit(limit)

        result = await self._session.scalars(statement)
        return list(result.all())
