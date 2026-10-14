from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.telemetry import TelemetryRecord
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate
from app.services.vehicle_service import VehicleService
from tests.conftest import unique_vin


@pytest_asyncio.fixture
async def session(clean_db, session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def vehicle_id(session: AsyncSession) -> UUID:
    vehicle = await VehicleService(session, VehicleRepository(session)).create_vehicle(
        VehicleCreate(vin=unique_vin(), make="Toyota", model="Camry", year=2024)
    )
    return vehicle.id


async def _persist(
    session: AsyncSession, vehicle_id: UUID, moment: datetime, rpm: float
) -> TelemetryRecord:
    record = await TelemetryRepository(session).create(
        TelemetryRecord(vehicle_id=vehicle_id, timestamp=moment, rpm=rpm)
    )
    await session.commit()
    return record


async def test_list_by_vehicle_is_newest_first_despite_insert_order(
    session: AsyncSession, vehicle_id: UUID
) -> None:
    """The table/explorer contract: page 1 starts at the newest sample even
    when rows were persisted out of chronological order."""
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # Persist oldest last to prove ordering comes from the query, not the insert.
    await _persist(session, vehicle_id, base + timedelta(seconds=20), 3000.0)
    await _persist(session, vehicle_id, base, 1000.0)
    await _persist(session, vehicle_id, base + timedelta(seconds=10), 2000.0)

    records, total = await TelemetryRepository(session).list_by_vehicle(
        vehicle_id, page=1, page_size=50
    )

    assert total == 3
    assert [r.timestamp for r in records] == [
        base + timedelta(seconds=20),
        base + timedelta(seconds=10),
        base,
    ]
    assert [r.rpm for r in records] == [3000.0, 2000.0, 1000.0]


async def test_list_since_cursor_is_exclusive_and_ascending(
    session: AsyncSession, vehicle_id: UUID
) -> None:
    """The SSE poll contract: strictly newer than the cursor, oldest first, so
    a timestamp read back from a batch never re-emits that batch's tail."""
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for offset in (0, 10, 20):
        await _persist(session, vehicle_id, base + timedelta(seconds=offset), 1000.0)

    records = await TelemetryRepository(session).list_since(
        vehicle_id, after=base + timedelta(seconds=10), limit=200
    )

    assert [r.timestamp for r in records] == [base + timedelta(seconds=20)]
