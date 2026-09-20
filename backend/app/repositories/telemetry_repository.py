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
