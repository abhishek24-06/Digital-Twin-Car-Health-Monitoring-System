from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.telemetry import TelemetryRecord
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate


class TelemetryService:
    """Business logic for telemetry ingestion and querying."""

    def __init__(
        self,
        session: AsyncSession,
        repository: TelemetryRepository,
        vehicle_repository: VehicleRepository,
    ) -> None:
        self._session = session
        self._repository = repository
        self._vehicle_repository = vehicle_repository

    async def _ensure_vehicle_exists(self, vehicle_id: UUID) -> None:
        if await self._vehicle_repository.get_by_id(vehicle_id) is None:
            raise NotFoundError("Vehicle")

    async def create_telemetry(self, vehicle_id: UUID, data: TelemetryCreate) -> TelemetryRecord:
        await self._ensure_vehicle_exists(vehicle_id)
        record = TelemetryRecord(vehicle_id=vehicle_id, **data.model_dump())
        created = await self._repository.create(record)
        await self._session.commit()
        return created

    async def list_vehicle_telemetry(
        self,
        vehicle_id: UUID,
        *,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[list[TelemetryRecord], int]:
        await self._ensure_vehicle_exists(vehicle_id)
        return await self._repository.list_by_vehicle(
            vehicle_id,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
        )
