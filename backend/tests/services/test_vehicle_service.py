import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import ConflictError, NotFoundError
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.services.vehicle_service import VehicleService
from tests.conftest import unique_vin


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession], clean_db) -> AsyncSession:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
def service(session: AsyncSession) -> VehicleService:
    return VehicleService(session=session, repository=VehicleRepository(session))


def create_payload(vin: str | None = None) -> VehicleCreate:
    return VehicleCreate(
        vin=vin or unique_vin(),
        make="Toyota",
        model="Camry",
        year=2024,
        engine_type="2.5L Petrol",
    )


async def test_create_and_get_vehicle(service: VehicleService) -> None:
    vehicle = await service.create_vehicle(create_payload())

    fetched = await service.get_vehicle(vehicle.id)

    assert fetched.id == vehicle.id
    assert fetched.vin == vehicle.vin


async def test_create_duplicate_vin_raises_conflict(service: VehicleService) -> None:
    vin = unique_vin()
    await service.create_vehicle(create_payload(vin=vin))

    with pytest.raises(ConflictError):
        await service.create_vehicle(create_payload(vin=vin))


async def test_get_missing_vehicle_raises_not_found(service: VehicleService) -> None:
    with pytest.raises(NotFoundError):
        await service.get_vehicle(uuid.uuid4())


async def test_update_vehicle_partial(service: VehicleService) -> None:
    vehicle = await service.create_vehicle(create_payload())

    updated = await service.update_vehicle(vehicle.id, VehicleUpdate(make="Honda", year=2025))

    assert updated.make == "Honda"
    assert updated.year == 2025
    assert updated.model == "Camry"
    assert updated.vin == vehicle.vin


async def test_delete_vehicle(service: VehicleService) -> None:
    vehicle = await service.create_vehicle(create_payload())

    await service.delete_vehicle(vehicle.id)

    with pytest.raises(NotFoundError):
        await service.get_vehicle(vehicle.id)


async def test_list_vehicles_paginates(service: VehicleService) -> None:
    for _ in range(3):
        await service.create_vehicle(create_payload())

    items, total = await service.list_vehicles(page=1, page_size=2)

    assert total == 3
    assert len(items) == 2
