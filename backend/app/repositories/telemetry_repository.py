from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryRecord

logger = logging.getLogger(__name__)

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
    "simulation_run_id",
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
        run_id: UUID | None = None,
        exclude_run_id: UUID | None = None,
    ) -> list[TelemetryRecord]:
        """Efficiently retrieve a chronological telemetry window.

        Inclusive bounds on ``timestamp``; ordered oldest-first. Uses the
        existing ``(vehicle_id, timestamp)`` index (or the run-aware index when
        ``run_id`` is supplied). ``limit`` bounds the rows a caller may load; it
        keeps the *newest* rows in the window (dropping the oldest) while still
        returning them oldest-first. ``run_id`` narrows to one run;
        ``exclude_run_id`` excludes one run (used to keep a current session out
        of its own historical baseline).
        """
        statement = select(TelemetryRecord).where(
            TelemetryRecord.vehicle_id == vehicle_id,
            TelemetryRecord.timestamp >= start_time,
            TelemetryRecord.timestamp <= end_time,
        )
        if run_id is not None:
            statement = statement.where(TelemetryRecord.simulation_run_id == run_id)
        elif exclude_run_id is not None:
            statement = statement.where(
                or_(
                    TelemetryRecord.simulation_run_id.is_(None),
                    TelemetryRecord.simulation_run_id != exclude_run_id,
                )
            )

        # A bounded caller limit must keep the *newest* rows in the window, not
        # the oldest: ordering ascending and applying LIMIT would silently drop
        # the freshest samples (the exact rows a live verdict needs). Query
        # newest-first when a limit is present, then restore chronological
        # (oldest-first) order so the callers' ordering contract is unchanged.
        if limit is None:
            statement = statement.order_by(
                TelemetryRecord.timestamp.asc(), TelemetryRecord.id.asc()
            )
        else:
            statement = statement.order_by(
                TelemetryRecord.timestamp.desc(), TelemetryRecord.id.desc()
            ).limit(limit)

        result = await self._session.scalars(statement)
        records = list(result.all())
        if limit is not None:
            records.reverse()
            if len(records) == limit:
                logger.warning(
                    "telemetry window truncated to %s newest rows "
                    "(vehicle_id=%s window=[%s, %s] run_id=%s exclude_run_id=%s); "
                    "the oldest rows in the window were dropped",
                    limit,
                    vehicle_id,
                    start_time,
                    end_time,
                    run_id,
                    exclude_run_id,
                )
        return records

    async def get_run_timestamp_bounds(
        self,
        vehicle_id: UUID,
        run_id: UUID,
        *,
        after: datetime | None = None,
    ) -> tuple[datetime, datetime] | None:
        """Earliest and newest source timestamps persisted for one run.

        Returns ``None`` when the run has no persisted rows. ``after`` bounds
        the search from below (the analysis window), giving the session start
        within the window even when the run predates it.
        """
        filters = [
            TelemetryRecord.vehicle_id == vehicle_id,
            TelemetryRecord.simulation_run_id == run_id,
        ]
        if after is not None:
            filters.append(TelemetryRecord.timestamp >= after)
        row = await self._session.execute(
            select(
                func.min(TelemetryRecord.timestamp),
                func.max(TelemetryRecord.timestamp),
            ).where(*filters)
        )
        first_ts, last_ts = row.one()
        if first_ts is None or last_ts is None:
            return None
        return first_ts, last_ts

    async def get_run_segments(
        self,
        vehicle_id: UUID,
        *,
        start_time: datetime,
        end_time: datetime,
    ) -> list[tuple[UUID | None, int, datetime, datetime]]:
        """Per-run boundary segments within a time window.

        Returns ``(run_id, sample_count, first_ts, last_ts)`` per distinct
        persisted ``simulation_run_id`` (including a legacy ``None`` segment
        for rows without provenance), ordered by the segment's first sample.
        Backed by the ``(vehicle_id, simulation_run_id, timestamp)`` index.
        """
        rows = await self._session.execute(
            select(
                TelemetryRecord.simulation_run_id,
                func.count(),
                func.min(TelemetryRecord.timestamp),
                func.max(TelemetryRecord.timestamp),
            )
            .where(
                TelemetryRecord.vehicle_id == vehicle_id,
                TelemetryRecord.timestamp >= start_time,
                TelemetryRecord.timestamp <= end_time,
            )
            .group_by(TelemetryRecord.simulation_run_id)
            .order_by(func.min(TelemetryRecord.timestamp).asc())
        )
        return [
            (run_id, count, first_ts, last_ts)
            for run_id, count, first_ts, last_ts in rows.all()
        ]

    async def get_latest_run_record(
        self,
        vehicle_id: UUID,
        run_id: UUID,
        *,
        after: datetime | None = None,
    ) -> TelemetryRecord | None:
        """Newest persisted row belonging to one active run.

        Returns both the source timestamp and the DB persistence time
        (``created_at``) of the freshest current-run sample so callers can
        separate measurement chronology from ingestion time.
        """
        filters = [
            TelemetryRecord.vehicle_id == vehicle_id,
            TelemetryRecord.simulation_run_id == run_id,
        ]
        if after is not None:
            filters.append(TelemetryRecord.timestamp >= after)
        statement = (
            select(TelemetryRecord)
            .where(*filters)
            .order_by(TelemetryRecord.timestamp.desc(), TelemetryRecord.id.desc())
            .limit(1)
        )
        return await self._session.scalar(statement)

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
