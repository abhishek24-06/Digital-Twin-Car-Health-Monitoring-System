from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DatabaseError, NotFoundError
from app.models.telemetry import TelemetryRecord
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate

logger = logging.getLogger(__name__)


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
        """Persist a telemetry sample, skipping duplicates by source_event_id.

        Idempotency: if the caller supplies a ``source_event_id`` and a record
        for that vehicle already exists with the same event id, the existing
        record is returned without inserting a new row. A unique constraint
        violation is treated as a duplicate as a backstop for concurrent
        deliveries.
        """
        await self._ensure_vehicle_exists(vehicle_id)

        if data.source_event_id is not None:
            existing = await self._repository.get_by_source_event(vehicle_id, data.source_event_id)
            if existing is not None:
                logger.debug(
                    "Skipping duplicate event_id=%s for vehicle %s",
                    data.source_event_id,
                    vehicle_id,
                )
                return existing

        record = TelemetryRecord(vehicle_id=vehicle_id, **data.model_dump())
        try:
            created = await self._repository.create(record)
        except IntegrityError as exc:
            await self._session.rollback()
            if data.source_event_id is None:
                raise DatabaseError("Failed to persist telemetry sample") from exc
            duplicate = await self._repository.get_by_source_event(vehicle_id, data.source_event_id)
            if duplicate is not None:
                logger.debug(
                    "Duplicate event_id=%s for vehicle %s after unique constraint",
                    data.source_event_id,
                    vehicle_id,
                )
                return duplicate
            raise DatabaseError("Failed to persist telemetry sample") from exc

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
