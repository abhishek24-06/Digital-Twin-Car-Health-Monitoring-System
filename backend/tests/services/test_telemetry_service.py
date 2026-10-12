from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import NotFoundError
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate
from app.schemas.vehicle import VehicleCreate
from app.services.telemetry_service import TelemetryService
from app.services.vehicle_service import VehicleService
from tests.conftest import unique_vin


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession], clean_db) -> AsyncSession:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
def service(session: AsyncSession) -> TelemetryService:
    return TelemetryService(
        session=session,
        repository=TelemetryRepository(session),
        vehicle_repository=VehicleRepository(session),
    )


@pytest_asyncio.fixture
async def existing_vehicle(session: AsyncSession) -> UUID:
    vehicle_service = VehicleService(session, VehicleRepository(session))
    vehicle = await vehicle_service.create_vehicle(
        VehicleCreate(
            vin=unique_vin(),
            make="Toyota",
            model="Corolla",
            year=2023,
        )
    )
    return vehicle.id


def telemetry_at(offset_hours: int) -> TelemetryCreate:
    timestamp = datetime.now(UTC) - timedelta(hours=offset_hours)
    return TelemetryCreate(
        timestamp=timestamp,
        rpm=float(offset_hours * 500),
        speed=50.0,
    )


async def test_create_telemetry_for_existing_vehicle(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    record = await service.create_telemetry(existing_vehicle, telemetry_at(1))

    assert record.vehicle_id == existing_vehicle
    assert record.rpm == 500.0


async def test_create_telemetry_for_missing_vehicle_raises_not_found(
    service: TelemetryService,
) -> None:
    with pytest.raises(NotFoundError):
        await service.create_telemetry(uuid4(), telemetry_at(1))


async def test_create_telemetry_persists_supplied_run_id(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    """The REST ingestion path persists a client-declared run identity."""
    run_id = uuid4()
    record = await service.create_telemetry(
        existing_vehicle,
        TelemetryCreate(timestamp=datetime.now(UTC), rpm=500.0, simulation_run_id=run_id),
    )
    assert record.simulation_run_id == run_id


async def test_create_telemetry_without_run_id_stays_null(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    """A sample with no run identity is stored as NULL -- never fabricated."""
    record = await service.create_telemetry(existing_vehicle, telemetry_at(1))
    assert record.simulation_run_id is None


async def test_list_telemetry_newest_first(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    for hours in (3, 2, 1):
        await service.create_telemetry(existing_vehicle, telemetry_at(hours))

    items, total = await service.list_vehicle_telemetry(existing_vehicle, page=1, page_size=10)

    assert total == 3
    rpms = [item.rpm for item in items]
    assert rpms == sorted(rpms)


async def test_list_telemetry_time_filtering(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    now = datetime.now(UTC)
    t1 = now - timedelta(hours=3)
    t2 = now - timedelta(hours=2)
    t3 = now - timedelta(hours=1)
    for timestamp, rpm in [(t1, 100.0), (t2, 200.0), (t3, 300.0)]:
        await service.create_telemetry(
            existing_vehicle, TelemetryCreate(timestamp=timestamp, rpm=rpm)
        )

    _, total = await service.list_vehicle_telemetry(
        existing_vehicle,
        page=1,
        page_size=10,
        start_time=t2,
        end_time=t3,
    )
    assert total == 2

    _, total = await service.list_vehicle_telemetry(
        existing_vehicle,
        page=1,
        page_size=10,
        end_time=t1,
    )
    assert total == 1

    _, total = await service.list_vehicle_telemetry(
        existing_vehicle,
        page=1,
        page_size=10,
        start_time=t2,
    )
    assert total == 2


async def test_list_telemetry_for_missing_vehicle_raises_not_found(
    service: TelemetryService,
) -> None:
    with pytest.raises(NotFoundError):
        await service.list_vehicle_telemetry(uuid4(), page=1, page_size=10)


async def test_duplicate_source_event_skipped(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    data = TelemetryCreate(
        timestamp=datetime.now(UTC),
        rpm=1500.0,
        source_event_id="event-1",
    )
    first = await service.create_telemetry(existing_vehicle, data)
    second = await service.create_telemetry(existing_vehicle, data)

    assert first.id == second.id
    items, total = await service.list_vehicle_telemetry(existing_vehicle, page=1, page_size=10)
    assert total == 1


async def test_distinct_source_events_both_created(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    await service.create_telemetry(
        existing_vehicle,
        TelemetryCreate(timestamp=datetime.now(UTC), rpm=100.0, source_event_id="event-1"),
    )
    await service.create_telemetry(
        existing_vehicle,
        TelemetryCreate(timestamp=datetime.now(UTC), rpm=200.0, source_event_id="event-2"),
    )

    _, total = await service.list_vehicle_telemetry(existing_vehicle, page=1, page_size=10)
    assert total == 2


async def test_same_source_event_allowed_across_vehicles(
    session: AsyncSession, existing_vehicle: UUID
) -> None:
    other_service = TelemetryService(
        session=session,
        repository=TelemetryRepository(session),
        vehicle_repository=VehicleRepository(session),
    )
    other_vehicle = await VehicleService(session, VehicleRepository(session)).create_vehicle(
        VehicleCreate(vin=unique_vin(), make="Honda", model="Accord", year=2022)
    )

    data = TelemetryCreate(timestamp=datetime.now(UTC), rpm=900.0, source_event_id="shared")
    await other_service.create_telemetry(existing_vehicle, data)
    await other_service.create_telemetry(other_vehicle.id, data)

    _, total = await other_service.list_vehicle_telemetry(existing_vehicle, page=1, page_size=10)
    assert total == 1
    _, total = await other_service.list_vehicle_telemetry(other_vehicle.id, page=1, page_size=10)
    assert total == 1


async def test_integrity_error_backstop_returns_existing(
    session_factory, existing_vehicle: UUID
) -> None:
    """Simulates the concurrent-write race: the pre-check misses the row, the
    insert hits the unique constraint, and the service recovers by returning
    the existing record from the IntegrityError handler."""
    data = TelemetryCreate(timestamp=datetime.now(UTC), rpm=10.0, source_event_id="dup")

    async with session_factory() as session:
        service = TelemetryService(
            session,
            TelemetryRepository(session),
            VehicleRepository(session),
        )
        created = await service.create_telemetry(existing_vehicle, data)

    async with session_factory() as session:
        repository = TelemetryRepository(session)
        original = repository.get_by_source_event
        calls = 0

        async def racing_precheck(vehicle_id, source_event_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None  # race: another writer committed after our pre-check
            return await original(vehicle_id, source_event_id)

        repository.get_by_source_event = racing_precheck  # type: ignore[method-assign]
        service = TelemetryService(session, repository, VehicleRepository(session))
        result = await service.create_telemetry(existing_vehicle, data)

    assert result.id == created.id
    assert calls >= 2

    async with session_factory() as session:
        _, total = await TelemetryService(
            session, TelemetryRepository(session), VehicleRepository(session)
        ).list_vehicle_telemetry(existing_vehicle, page=1, page_size=10)
        assert total == 1


async def test_ingest_batch_persists_every_row(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    now = datetime.now(UTC)
    run_id = uuid4()
    items = [
        (
            existing_vehicle,
            TelemetryCreate(
                timestamp=now,
                rpm=float(i),
                source_event_id=f"batch-{i}",
                simulation_run_id=run_id,
            ),
        )
        for i in range(50)
    ]

    result = await service.ingest_batch(items)

    assert result.submitted == 50
    assert result.inserted == 50
    assert result.duplicates == 0
    assert result.unknown_vehicle_ids == set()
    items, _ = await service.list_vehicle_telemetry(existing_vehicle, page=1, page_size=100)
    assert len(items) == 50
    assert all(item.simulation_run_id == run_id for item in items)


async def test_ingest_batch_is_idempotent_by_source_event(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    now = datetime.now(UTC)
    item = (
        existing_vehicle,
        TelemetryCreate(timestamp=now, rpm=1.0, source_event_id="duplicate"),
    )

    result = await service.ingest_batch([item, item, item])

    assert result.submitted == 3
    assert result.inserted == 1
    assert result.duplicates == 2
    _, total = await service.list_vehicle_telemetry(existing_vehicle, page=1, page_size=100)
    assert total == 1


async def test_ingest_batch_skips_unknown_vehicle_without_aborting(
    service: TelemetryService, existing_vehicle: UUID
) -> None:
    unknown = uuid4()
    now = datetime.now(UTC)

    result = await service.ingest_batch(
        [
            (
                existing_vehicle,
                TelemetryCreate(timestamp=now, rpm=2.0, source_event_id="known"),
            ),
            (
                unknown,
                TelemetryCreate(timestamp=now, rpm=3.0, source_event_id="orphan"),
            ),
        ]
    )

    assert result.inserted == 1
    assert result.unknown_vehicle_ids == {unknown}
    _, total = await service.list_vehicle_telemetry(existing_vehicle, page=1, page_size=100)
    assert total == 1


async def test_ingest_batch_timestamps_are_immediately_queryable(
    service: TelemetryService, session: AsyncSession, existing_vehicle: UUID
) -> None:
    """Ingestion-to-query consistency: a freshly batch-written sample inside the
    health window must be visible to the window query the health engine uses."""
    now = datetime.now(UTC)
    timestamp = now - timedelta(seconds=1)
    await service.ingest_batch(
        [
            (
                existing_vehicle,
                TelemetryCreate(timestamp=timestamp, rpm=float(i), source_event_id=f"w-{i}"),
            )
            for i in range(5)
        ]
    )

    records = await TelemetryRepository(session).get_recent_telemetry(
        existing_vehicle,
        start_time=now - timedelta(minutes=15),
        end_time=now,
    )

    assert len(records) == 5
    assert all(record.timestamp == timestamp for record in records)


async def test_get_recent_telemetry_limit_keeps_newest_rows(
    service: TelemetryService, session: AsyncSession, existing_vehicle: UUID
) -> None:
    """A bounded window query must keep the newest samples, not the oldest.

    Ordering ascending and applying ``LIMIT`` (the pre-fix behavior) silently
    dropped the freshest rows -- exactly the rows a live verdict depends on.
    """
    now = datetime.now(UTC)
    base = now - timedelta(seconds=10)
    await service.ingest_batch(
        [
            (
                existing_vehicle,
                TelemetryCreate(
                    timestamp=base + timedelta(seconds=i),
                    rpm=float(i),
                    source_event_id=f"limit-{i}",
                ),
            )
            for i in range(10)
        ]
    )

    records = await TelemetryRepository(session).get_recent_telemetry(
        existing_vehicle,
        start_time=base,
        end_time=now,
        limit=4,
    )

    # Newest four kept, still returned chronologically (oldest-first).
    assert [record.rpm for record in records] == [6.0, 7.0, 8.0, 9.0]
    assert records == sorted(records, key=lambda record: record.timestamp)
