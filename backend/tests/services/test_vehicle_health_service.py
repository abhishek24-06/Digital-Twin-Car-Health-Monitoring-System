from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import NotFoundError
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate
from app.schemas.vehicle import VehicleCreate
from app.services.telemetry_service import TelemetryService
from app.services.vehicle_health_service import VehicleHealthService
from app.services.vehicle_service import VehicleService
from tests.conftest import unique_vin


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
def service(session: AsyncSession) -> VehicleHealthService:
    return VehicleHealthService(
        session=session,
        vehicle_repository=VehicleRepository(session),
        telemetry_repository=TelemetryRepository(session),
        health_repository=HealthSnapshotRepository(session),
    )


@pytest_asyncio.fixture
def telemetry_service(session: AsyncSession) -> TelemetryService:
    return TelemetryService(
        session=session,
        repository=TelemetryRepository(session),
        vehicle_repository=VehicleRepository(session),
    )


def healthy_payload(rpm: float = 2000.0) -> TelemetryCreate:
    return TelemetryCreate(
        timestamp=datetime.now(UTC),
        rpm=rpm,
        speed=60.0,
        engine_load=30.0,
        coolant_temperature=90.0,
        oil_temperature=90.0,
        battery_voltage=13.5,
        fuel_level=60.0,
        intake_air_temperature=25.0,
        throttle_position=20.0,
        engine_runtime=1000.0,
        odometer=50000.0,
    )


async def _create_vehicle(session: AsyncSession) -> UUID:
    vehicle = await VehicleService(session, VehicleRepository(session)).create_vehicle(
        VehicleCreate(vin=unique_vin(), make="Toyota", model="Camry", year=2024)
    )
    return vehicle.id


async def _ingest_healthy_window(telemetry_service: TelemetryService, vehicle_id: UUID) -> None:
    now = datetime.now(UTC)
    for index in range(40):
        payload = healthy_payload()
        payload.timestamp = now - timedelta(seconds=40 - index)
        await telemetry_service.create_telemetry(vehicle_id, payload)


async def test_analyze_vehicle_persists_snapshot(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)

    snapshot = await service.analyze_vehicle(vehicle_id, window_minutes=1)

    assert snapshot.vehicle_id == vehicle_id
    assert snapshot.health_status == "healthy"
    assert snapshot.health_score == 100.0
    assert snapshot.context_schema_version == "1.0"
    assert snapshot.context_json["health_status"] == "healthy"
    assert snapshot.confidence is not None and 0.5 < snapshot.confidence <= 1.0

    latest = await service.get_latest(vehicle_id)
    assert latest is not None
    assert latest.id == snapshot.id


async def test_analyze_vehicle_respects_window_minutes(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)

    snapshot = await service.analyze_vehicle(vehicle_id, window_minutes=2)

    window_seconds = (snapshot.window_end - snapshot.window_start).total_seconds()
    assert 110.0 <= window_seconds <= 130.0


async def test_analyze_missing_vehicle_raises_not_found(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    with pytest.raises(NotFoundError):
        await service.analyze_vehicle(uuid4(), window_minutes=1)


async def test_analyze_invalid_window_minutes_raises_value_error(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)
    with pytest.raises(ValueError):
        await service.analyze_vehicle(vehicle_id, window_minutes=0)


async def test_get_latest_none_before_any_analysis(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    assert await service.get_latest(vehicle_id) is None


async def test_get_latest_missing_vehicle_raises_not_found(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    with pytest.raises(NotFoundError):
        await service.get_latest(uuid4())


async def test_list_history_paginated_and_latest_first(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)
    await service.analyze_vehicle(vehicle_id, window_minutes=1)
    await service.analyze_vehicle(vehicle_id, window_minutes=1)

    items, total = await service.list_history(vehicle_id, page=1, page_size=1)
    assert total == 2
    assert len(items) == 1
    assert items[0].generated_at >= items[0].window_end


async def test_list_history_missing_vehicle_raises_not_found(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    with pytest.raises(NotFoundError):
        await service.list_history(uuid4(), page=1, page_size=10)


async def test_repeat_analysis_creates_new_snapshot(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)
    first = await service.analyze_vehicle(vehicle_id, window_minutes=1)
    second = await service.analyze_vehicle(vehicle_id, window_minutes=1)

    assert first.id != second.id
    items, total = await service.list_history(vehicle_id, page=1, page_size=10)
    assert total == 2
