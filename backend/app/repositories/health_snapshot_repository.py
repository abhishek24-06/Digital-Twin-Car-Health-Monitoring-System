from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.health_snapshot import HealthSnapshot


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
