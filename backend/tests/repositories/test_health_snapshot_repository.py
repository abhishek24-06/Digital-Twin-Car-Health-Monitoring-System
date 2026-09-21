from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.health_snapshot import HealthSnapshot
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate
from app.services.vehicle_service import VehicleService
from tests.conftest import unique_vin


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def vehicle_id(session: AsyncSession) -> UUID:
    vehicle = await VehicleService(session, VehicleRepository(session)).create_vehicle(
        VehicleCreate(vin=unique_vin(), make="Toyota", model="Camry", year=2024)
    )
    return vehicle.id


def make_snapshot(
    vehicle_id: UUID, ts: datetime, health_status: str = "healthy", score: float | None = 100.0
) -> HealthSnapshot:
    return HealthSnapshot(
        vehicle_id=vehicle_id,
        generated_at=ts,
        window_start=ts - timedelta(minutes=1),
        window_end=ts,
        sample_count=60,
        health_score=score,
        health_status=health_status,
        confidence=0.9,
        context_schema_version="1.0",
        context_json={"vehicle_id": str(vehicle_id), "health_status": health_status},
    )


async def test_create_and_get_by_id(session: AsyncSession, vehicle_id: UUID) -> None:
    repo = HealthSnapshotRepository(session)
    snapshot = make_snapshot(vehicle_id, datetime.now(UTC))
    created = await repo.create(snapshot)
    await session.commit()

    assert created.id is not None
    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.vehicle_id == vehicle_id
    assert fetched.context_json["health_status"] == "healthy"


async def test_get_latest_returns_most_recent(session: AsyncSession, vehicle_id: UUID) -> None:
    repo = HealthSnapshotRepository(session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await repo.create(make_snapshot(vehicle_id, base))
    latest = await repo.create(make_snapshot(vehicle_id, base + timedelta(minutes=30)))
    await session.commit()

    fetched = await repo.get_latest_by_vehicle(vehicle_id)
    assert fetched is not None
    assert fetched.id == latest.id


async def test_get_latest_none_when_empty(session: AsyncSession, vehicle_id: UUID) -> None:
    repo = HealthSnapshotRepository(session)
    assert await repo.get_latest_by_vehicle(vehicle_id) is None


async def test_list_pagination_newest_first(session: AsyncSession, vehicle_id: UUID) -> None:
    repo = HealthSnapshotRepository(session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(5):
        await repo.create(make_snapshot(vehicle_id, base + timedelta(minutes=index)))
    await session.commit()

    page_one, total = await repo.list_by_vehicle(vehicle_id, page=1, page_size=2)
    assert total == 5
    assert [s.generated_at for s in page_one] == [
        base + timedelta(minutes=4),
        base + timedelta(minutes=3),
    ]


async def test_list_time_filtering(session: AsyncSession, vehicle_id: UUID) -> None:
    repo = HealthSnapshotRepository(session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = base + timedelta(hours=1)
    t2 = base + timedelta(hours=2)
    t3 = base + timedelta(hours=3)
    for ts in (t1, t2, t3):
        await repo.create(make_snapshot(vehicle_id, ts))
    await session.commit()

    _, total = await repo.list_by_vehicle(
        vehicle_id, page=1, page_size=10, start_time=t2, end_time=t3
    )
    assert total == 2

    _, total = await repo.list_by_vehicle(vehicle_id, page=1, page_size=10, end_time=t1)
    assert total == 1


async def test_snapshots_isolated_per_vehicle(session: AsyncSession, vehicle_id: UUID) -> None:
    repo = HealthSnapshotRepository(session)
    other = await VehicleService(session, VehicleRepository(session)).create_vehicle(
        VehicleCreate(vin=unique_vin(), make="Honda", model="Accord", year=2023)
    )
    await repo.create(make_snapshot(vehicle_id, datetime(2026, 1, 1, tzinfo=UTC)))
    await repo.create(make_snapshot(other.id, datetime(2026, 1, 1, tzinfo=UTC)))
    await session.commit()

    _, total = await repo.list_by_vehicle(vehicle_id, page=1, page_size=10)
    assert total == 1


async def test_orphan_snapshot_requires_vehicle(session: AsyncSession) -> None:
    repo = HealthSnapshotRepository(session)
    orphan = make_snapshot(uuid4(), datetime.now(UTC))
    with pytest.raises(IntegrityError):
        await repo.create(orphan)
