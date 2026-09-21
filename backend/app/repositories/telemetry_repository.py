from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryRecord


class TelemetryRepository:
    """Data access for telemetry records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: TelemetryRecord) -> TelemetryRecord:
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def get_by_source_event(
        self, vehicle_id: UUID, source_event_id: str
    ) -> TelemetryRecord | None:
        statement = select(TelemetryRecord).where(
            TelemetryRecord.vehicle_id == vehicle_id,
            TelemetryRecord.source_event_id == source_event_id,
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
    ) -> tuple[list[TelemetryRecord], int]:
        filters = [TelemetryRecord.vehicle_id == vehicle_id]
        if start_time is not None:
            filters.append(TelemetryRecord.timestamp >= start_time)
        if end_time is not None:
            filters.append(TelemetryRecord.timestamp <= end_time)

        total = await self._session.scalar(
            select(func.count()).select_from(TelemetryRecord).where(*filters)
        )

        statement = (
            select(TelemetryRecord)
            .where(*filters)
            .order_by(TelemetryRecord.timestamp.desc(), TelemetryRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.scalars(statement)
        return list(result.all()), int(total or 0)

    async def get_recent_telemetry(
        self,
        vehicle_id: UUID,
        *,
        start_time: datetime,
        end_time: datetime,
        limit: int | None = None,
    ) -> list[TelemetryRecord]:
        """Efficiently retrieve a chronological telemetry window.

        Inclusive bounds on ``timestamp``; ordered oldest-first. Uses the
        existing ``(vehicle_id, timestamp)`` index. ``limit`` bounds the rows
        a caller may load.
        """
        statement = (
            select(TelemetryRecord)
            .where(
                TelemetryRecord.vehicle_id == vehicle_id,
                TelemetryRecord.timestamp >= start_time,
                TelemetryRecord.timestamp <= end_time,
            )
            .order_by(TelemetryRecord.timestamp.asc(), TelemetryRecord.id.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.scalars(statement)
        return list(result.all())
