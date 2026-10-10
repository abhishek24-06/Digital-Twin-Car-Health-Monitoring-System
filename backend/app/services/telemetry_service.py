from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DatabaseError, NotFoundError
from app.models.telemetry import TelemetryRecord
from app.models.user import User
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate
from app.services.vehicle_access import ensure_vehicle_access

logger = logging.getLogger(__name__)


@dataclass
class BatchIngestResult:
    """Outcome of a batched telemetry write (counts, not rows)."""

    submitted: int = 0
    inserted: int = 0
    duplicates: int = 0
    unknown_vehicle_ids: set[UUID] = field(default_factory=set)


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

    async def create_telemetry_for_user(
        self, vehicle_id: UUID, data: TelemetryCreate, user: User
    ) -> TelemetryRecord:
        """User-scoped ingest: ownership is enforced below the router."""
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self.create_telemetry(vehicle_id, data)

    async def list_vehicle_telemetry_for_user(
        self,
        vehicle_id: UUID,
        user: User,
        *,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[list[TelemetryRecord], int]:
        """User-scoped listing: ownership is enforced below the router."""
        await ensure_vehicle_access(self._vehicle_repository, vehicle_id, user)
        return await self.list_vehicle_telemetry(
            vehicle_id,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
        )

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

    async def ingest_batch(
        self, items: Sequence[tuple[UUID, TelemetryCreate]]
    ) -> BatchIngestResult:
        """Persist many telemetry samples with a single database write.

        This is the subscriber's hot path. Instead of one existence check, one
        duplicate pre-check, one insert and one refresh round trip *per message*,
        a whole batch is validated with one query and written with one
        ``INSERT ... ON CONFLICT DO NOTHING``. Idempotency semantics match
        :meth:`create_telemetry`: rows whose ``(vehicle_id, source_event_id)``
        already exist are skipped rather than duplicated, and messages for
        vehicles that do not exist are dropped (reported to the caller) instead
        of aborting the batch.
        """
        result = BatchIngestResult(submitted=len(items))
        if not items:
            return result

        known = await self._vehicle_repository.existing_ids({vehicle_id for vehicle_id, _ in items})
        records: list[TelemetryRecord] = []
        for vehicle_id, data in items:
            if vehicle_id not in known:
                result.unknown_vehicle_ids.add(vehicle_id)
                continue
            records.append(TelemetryRecord(id=uuid4(), vehicle_id=vehicle_id, **data.model_dump()))

        try:
            result.inserted = await self._repository.insert_many(records)
        except IntegrityError as exc:
            await self._session.rollback()
            raise DatabaseError("Failed to persist telemetry batch") from exc

        await self._session.commit()
        result.duplicates = len(records) - result.inserted
        return result

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
