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
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
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
