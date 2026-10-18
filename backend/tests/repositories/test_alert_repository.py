from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.alert import Alert
from app.repositories.alert_repository import ActiveAlertCounts, AlertRepository
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


def make_alert(
    vehicle_id: UUID,
    *,
    dedup_suffix: str,
    severity: str = "warning",
    status: str = "open",
) -> Alert:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Alert(
        vehicle_id=vehicle_id,
        dedup_key=f"{vehicle_id}:{dedup_suffix}",
        rule_id="COOLANT_TEMP_HIGH",
        severity=severity,
        status=status,
        title="Coolant temperature high",
        message="Coolant temperature exceeded the configured threshold.",
        occurrence_count=1,
        first_seen_at=now,
        last_seen_at=now,
    )


async def test_count_active_by_vehicles_groups_and_filters(
    session: AsyncSession, vehicle_id: UUID
) -> None:
    repo = AlertRepository(session)
    vehicle_service = VehicleService(session, VehicleRepository(session))
    empty = await vehicle_service.create_vehicle(
        VehicleCreate(vin=unique_vin(), make="Honda", model="Civic", year=2023)
    )

    await repo.create(make_alert(vehicle_id, dedup_suffix="A", severity="critical", status="open"))
    await repo.create(
        make_alert(vehicle_id, dedup_suffix="B", severity="warning", status="acknowledged")
    )
    # A resolved alert is historical evidence and must not be counted.
    await repo.create(
        make_alert(vehicle_id, dedup_suffix="C", severity="critical", status="resolved")
    )
    await session.commit()

    counts = await repo.count_active_by_vehicles([vehicle_id, empty.id])

    assert counts[vehicle_id] == ActiveAlertCounts(active=2, critical=1, warning=1)
    assert empty.id not in counts


async def test_count_active_by_vehicles_empty_input(session: AsyncSession) -> None:
    repo = AlertRepository(session)
    assert await repo.count_active_by_vehicles([]) == {}


async def test_count_active_by_vehicles_unknown_vehicle_absent(session: AsyncSession) -> None:
    repo = AlertRepository(session)
    assert await repo.count_active_by_vehicles([uuid4()]) == {}
