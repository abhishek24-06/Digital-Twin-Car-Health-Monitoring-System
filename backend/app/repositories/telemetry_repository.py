from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryRecord

# Columns written by ``insert_many``. ``created_at``/``updated_at`` are omitted so
# the database server defaults apply (same as a normal ORM insert).
_INSERT_COLUMNS = (
    "id",
    "vehicle_id",
    "timestamp",
    "rpm",
    "speed",
    "engine_load",
    "coolant_temperature",
    "oil_temperature",
    "battery_voltage",
    "fuel_level",
    "intake_air_temperature",
    "throttle_position",
    "engine_runtime",
    "odometer",
    "raw_payload",
    "source_event_id",
)


class TelemetryRepository:
    """Data access for telemetry records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: TelemetryRecord) -> TelemetryRecord:
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def insert_many(self, records: list[TelemetryRecord]) -> int:
        """Persist many records in one statement, skipping duplicates.

        Idempotency is preserved by the ``(vehicle_id, source_event_id)`` unique
        index: conflicting rows are ignored rather than failing the batch
        (``ON CONFLICT DO NOTHING``). Returns the number of rows actually
        inserted, so callers can tell duplicates apart from new samples.
        """
        if not records:
            return 0
        values = [
            {column: getattr(record, column) for column in _INSERT_COLUMNS} for record in records
        ]
        statement = pg_insert(TelemetryRecord).values(values).on_conflict_do_nothing()
        result = await self._session.execute(statement)
        return int(result.rowcount or 0)

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

    async def list_since(
        self,
        vehicle_id: UUID,
        *,
        after: datetime,
        limit: int,
    ) -> list[TelemetryRecord]:
        """Return telemetry strictly newer than ``after``, oldest first.

        The exclusive ``timestamp`` bound makes a value read back from a
        previous batch a safe cursor (no record can be missed or emitted twice).
        Honors the ``(vehicle_id, timestamp)`` index; ``limit`` bounds how much
        a single poll may emit.
        """
        statement = (
            select(TelemetryRecord)
            .where(
                TelemetryRecord.vehicle_id == vehicle_id,
                TelemetryRecord.timestamp > after,
            )
            .order_by(TelemetryRecord.timestamp.asc(), TelemetryRecord.id.asc())
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def count_for_vehicle(self, vehicle_id: UUID) -> int:
        """Number of persisted telemetry rows for a vehicle (read-only)."""
        statement = (
            select(func.count())
            .select_from(TelemetryRecord)
            .where(TelemetryRecord.vehicle_id == vehicle_id)
        )
        return int(await self._session.scalar(statement) or 0)

    async def count_since(self, after: datetime) -> int:
        """Number of persisted telemetry rows strictly newer than ``after``.

        Read-only COUNT used by the workflow status endpoint as the "recent
        telemetry activity" recency signal; it deliberately avoids loading
        rows.
        """
        statement = (
            select(func.count())
            .select_from(TelemetryRecord)
            .where(TelemetryRecord.timestamp > after)
        )
        return int(await self._session.scalar(statement) or 0)

    async def get_latest_timestamps(self, vehicle_ids: list[UUID]) -> dict[UUID, datetime]:
        """Map each vehicle id to its newest telemetry timestamp.

        Vehicles with no telemetry are absent from the result so callers can
        distinguish "no samples" from a timestamp. An empty input returns an
        empty map without issuing a query.
        """
        if not vehicle_ids:
            return {}
        statement = (
            select(TelemetryRecord.vehicle_id, func.max(TelemetryRecord.timestamp))
            .where(TelemetryRecord.vehicle_id.in_(vehicle_ids))
            .group_by(TelemetryRecord.vehicle_id)
        )
        rows = await self._session.execute(statement)
        return {vehicle_id: latest for vehicle_id, latest in rows.all()}
