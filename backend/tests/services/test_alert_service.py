from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import ConflictError, NotFoundError
from app.models.alert import (
    ALERT_EVENT_ACKNOWLEDGED,
    ALERT_EVENT_CREATED,
    ALERT_EVENT_RECURRED,
    ALERT_EVENT_RESOLVED,
    ALERT_STATUS_ACKNOWLEDGED,
    ALERT_STATUS_OPEN,
    ALERT_STATUS_RESOLVED,
)
from app.models.user import User
from app.models.vehicle import Vehicle
from app.repositories.alert_repository import AlertRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.alert_service import AlertService, is_alert_worthy
from tests.conftest import unique_vin


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession], clean_db) -> AsyncSession:
    async with session_factory() as s:
        yield s


def _service(session: AsyncSession) -> AlertService:
    return AlertService(
        session=session,
        vehicle_repository=VehicleRepository(session),
        alert_repository=AlertRepository(session),
    )


async def _create_user(session: AsyncSession, *, role: str = "user") -> User:
    user = User(
        email=f"alert.{uuid4().hex[:8]}@example.com",
        password_hash="not-used",
        role=role,
        full_name="Alert Tester",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _create_vehicle(session: AsyncSession, owner_id: UUID | None) -> UUID:
    vehicle = Vehicle(
        vin=unique_vin(),
        make="Toyota",
        model="Camry",
        year=2024,
        owner_user_id=owner_id,
    )
    session.add(vehicle)
    await session.commit()
    await session.refresh(vehicle)
    return vehicle.id


def _finding(
    rule_id: str = "COOLANT_TEMP_HIGH",
    severity: str = "critical",
    *,
    category: str = "temperature",
    message: str = "Coolant temperature is significantly elevated.",
    observed: float = 120.0,
    threshold: float = 110.0,
    metric: str = "coolant_temperature",
    unit: str = "degC",
) -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "metric": metric,
        "observed_value": observed,
        "threshold": threshold,
        "unit": unit,
        "message": message,
        "confidence": 0.9,
        "evidence": {"sample_count": 40},
    }


def _snapshot(
    vehicle_id: UUID,
    findings: list[dict],
    *,
    provisional: bool = False,
    run_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        vehicle_id=vehicle_id,
        generated_at=datetime.now(UTC),
        context_json={
            "findings": findings,
            "provisional": provisional,
            "simulation_run_id": str(run_id) if run_id else None,
        },
    )


# --- worthiness predicate -------------------------------------------------


@pytest.mark.parametrize(
    ("rule_id", "severity", "category", "expected"),
    [
        ("COOLANT_TEMP_HIGH", "critical", "temperature", True),
        ("BATTERY_VOLTAGE_LOW", "warning", "electrical", True),
        ("RPM_UNUSUAL", "warning", "engine", True),
        ("TELEMETRY_GAP", "info", "data_quality", False),
        ("LOW_DATA_COVERAGE", "info", "data_quality", False),
        ("INSUFFICIENT_DATA", "info", "data_quality", False),
        ("LOW_DATA_COVERAGE", "warning", "data_quality", False),
        ("SOMETHING_NEW", "warning", "engine", True),
    ],
)
def test_is_alert_worthy(rule_id: str, severity: str, category: str, expected: bool) -> None:
    finding = {"rule_id": rule_id, "severity": severity, "category": category}
    assert is_alert_worthy(finding) is expected


async def test_sync_creates_alert_for_critical_finding(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)

    alerts = await service.sync_from_snapshot(
        SimpleNamespace(
            id=uuid4(),
            vehicle_id=vehicle_id,
            generated_at=datetime.now(UTC),
            context_json={"findings": [_finding()], "provisional": False},
        )
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.status == ALERT_STATUS_OPEN
    assert alert.severity == "critical"
    assert alert.occurrence_count == 1
    assert alert.first_seen_at == alert.last_seen_at
    events = await AlertRepository(session).list_events(alert.id)
    assert [e.event_type for e in events] == [ALERT_EVENT_CREATED]


async def test_sync_ignores_non_actionable_findings(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)

    findings = [
        _finding("TELEMETRY_GAP", "info", category="data_quality", metric="telemetry"),
        _finding("LOW_DATA_COVERAGE", "info", category="data_quality", metric="telemetry"),
        _finding("LOW_DATA_COVERAGE", "warning", category="data_quality", metric="telemetry"),
    ]
    alerts = await service.sync_from_snapshot(
        SimpleNamespace(
            id=uuid4(),
            vehicle_id=vehicle_id,
            generated_at=datetime.now(UTC),
            context_json={"findings": findings},
        )
    )

    assert alerts == []
    assert await AlertRepository(session).list_active_by_vehicle(vehicle_id) == []


async def test_sync_deduplicates_recurrence(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)
    snapshot = SimpleNamespace(
        id=uuid4(),
        vehicle_id=vehicle_id,
        generated_at=datetime.now(UTC),
        context_json={"findings": [_finding()]},
    )

    first = await service.sync_from_snapshot(snapshot)
    second = await service.sync_from_snapshot(snapshot)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].id == second[0].id
    assert second[0].occurrence_count == 2
    events = await AlertRepository(session).list_events(first[0].id)
    assert [e.event_type for e in events] == [ALERT_EVENT_CREATED, ALERT_EVENT_RECURRED]


async def test_sync_updates_severity_on_recurrence(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)

    def snapshot(severity: str):
        return SimpleNamespace(
            id=uuid4(),
            vehicle_id=vehicle_id,
            generated_at=datetime.now(UTC),
            context_json={"findings": [_finding(severity=severity)]},
        )

    await service.sync_from_snapshot(snapshot("warning"))
    alerts = await service.sync_from_snapshot(snapshot("critical"))

    assert alerts[0].severity == "critical"
    events = await AlertRepository(session).list_events(alerts[0].id)
    assert events[-1].event_type == ALERT_EVENT_RECURRED
    assert "severity" in (events[-1].note or "")


async def test_sync_auto_resolves_cleared_condition(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)

    await service.sync_from_snapshot(
        SimpleNamespace(
            id=uuid4(),
            vehicle_id=vehicle_id,
            generated_at=datetime.now(UTC),
            context_json={"findings": [_finding()]},
        )
    )
    # A definitive evaluation with no finding clears the condition.
    await service.sync_from_snapshot(
        SimpleNamespace(
            id=uuid4(),
            vehicle_id=vehicle_id,
            generated_at=datetime.now(UTC),
            context_json={"findings": [], "provisional": False},
        )
    )

    active = await AlertRepository(session).list_active_by_vehicle(vehicle_id)
    assert active == []
    alerts, _ = await service.list_for_user(
        vehicle_id, user, statuses=None, severity=None, page=1, page_size=10
    )
    assert alerts[0].status == ALERT_STATUS_RESOLVED
    assert alerts[0].resolved_by is None
    events = await AlertRepository(session).list_events(alerts[0].id)
    assert events[-1].event_type == ALERT_EVENT_RESOLVED
    assert events[-1].actor_user_id is None


async def test_sync_does_not_auto_resolve_while_provisional(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)

    await service.sync_from_snapshot(
        SimpleNamespace(
            id=uuid4(),
            vehicle_id=vehicle_id,
            generated_at=datetime.now(UTC),
            context_json={"findings": [_finding()]},
        )
    )
    # Insufficient data is not evidence the condition cleared: stay open.
    await service.sync_from_snapshot(
        SimpleNamespace(
            id=uuid4(),
            vehicle_id=vehicle_id,
            generated_at=datetime.now(UTC),
            context_json={"findings": [], "provisional": True},
        )
    )

    active = await AlertRepository(session).list_active_by_vehicle(vehicle_id)
    assert len(active) == 1
    assert active[0].status == ALERT_STATUS_OPEN


async def test_recurrence_after_resolution_creates_a_new_alert(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)
    snapshot = SimpleNamespace(
        id=uuid4(),
        vehicle_id=vehicle_id,
        generated_at=datetime.now(UTC),
        context_json={"findings": [_finding()]},
    )

    first = (await service.sync_from_snapshot(snapshot))[0]
    await service.resolve_for_user(vehicle_id, first.id, user, note="fixed")
    second = (await service.sync_from_snapshot(snapshot))[0]

    assert second.id != first.id
    # The resolved alert is preserved as history.
    resolved = await AlertRepository(session).get_by_id(first.id)
    assert resolved is not None
    assert resolved.status == ALERT_STATUS_RESOLVED


async def test_acknowledge_and_resolve_lifecycle(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)
    alert = (
        await service.sync_from_snapshot(
            SimpleNamespace(
                id=uuid4(),
                vehicle_id=vehicle_id,
                generated_at=datetime.now(UTC),
                context_json={"findings": [_finding()]},
            )
        )
    )[0]

    acknowledged = await service.acknowledge_for_user(vehicle_id, alert.id, user, note="looking")
    assert acknowledged.status == ALERT_STATUS_ACKNOWLEDGED
    assert acknowledged.acknowledged_by == user.id
    assert acknowledged.acknowledge_note == "looking"

    # Idempotent: a second acknowledge must not add history.
    again = await service.acknowledge_for_user(vehicle_id, alert.id, user)
    assert again.status == ALERT_STATUS_ACKNOWLEDGED

    resolved = await service.resolve_for_user(vehicle_id, alert.id, user, note="replaced sensor")
    assert resolved.status == ALERT_STATUS_RESOLVED
    assert resolved.resolved_by == user.id
    assert resolved.resolution_note == "replaced sensor"

    events = await AlertRepository(session).list_events(alert.id)
    assert [e.event_type for e in events] == [
        ALERT_EVENT_CREATED,
        ALERT_EVENT_ACKNOWLEDGED,
        ALERT_EVENT_RESOLVED,
    ]


async def test_resolve_is_idempotent(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)
    alert = (
        await service.sync_from_snapshot(
            SimpleNamespace(
                id=uuid4(),
                vehicle_id=vehicle_id,
                generated_at=datetime.now(UTC),
                context_json={"findings": [_finding()]},
            )
        )
    )[0]

    await service.resolve_for_user(vehicle_id, alert.id, user)
    await service.resolve_for_user(vehicle_id, alert.id, user)

    events = await AlertRepository(session).list_events(alert.id)
    assert [e.event_type for e in events] == [ALERT_EVENT_CREATED, ALERT_EVENT_RESOLVED]


async def test_acknowledging_resolved_alert_conflicts(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)
    alert = (
        await service.sync_from_snapshot(
            SimpleNamespace(
                id=uuid4(),
                vehicle_id=vehicle_id,
                generated_at=datetime.now(UTC),
                context_json={"findings": [_finding()]},
            )
        )
    )[0]
    await service.resolve_for_user(vehicle_id, alert.id, user)

    with pytest.raises(ConflictError):
        await service.acknowledge_for_user(vehicle_id, alert.id, user)


async def test_ownership_is_enforced(session: AsyncSession) -> None:
    owner = await _create_user(session)
    intruder = await _create_user(session)
    vehicle_id = await _create_vehicle(session, owner.id)
    service = _service(session)
    alert = (
        await service.sync_from_snapshot(
            SimpleNamespace(
                id=uuid4(),
                vehicle_id=vehicle_id,
                generated_at=datetime.now(UTC),
                context_json={"findings": [_finding()]},
            )
        )
    )[0]

    with pytest.raises(NotFoundError):
        await service.list_for_user(
            vehicle_id, intruder, statuses=None, severity=None, page=1, page_size=10
        )
    with pytest.raises(NotFoundError):
        await service.get_for_user(vehicle_id, alert.id, intruder)
    with pytest.raises(NotFoundError):
        await service.acknowledge_for_user(vehicle_id, alert.id, intruder)


async def test_list_orders_critical_first_and_filters(session: AsyncSession) -> None:
    user = await _create_user(session)
    vehicle_id = await _create_vehicle(session, user.id)
    service = _service(session)

    await service.sync_from_snapshot(
        SimpleNamespace(
            id=uuid4(),
            vehicle_id=vehicle_id,
            generated_at=datetime.now(UTC),
            context_json={
                "findings": [
                    _finding("BATTERY_VOLTAGE_LOW", "warning", category="electrical"),
                    _finding("COOLANT_TEMP_HIGH", "critical"),
                ]
            },
        )
    )

    alerts, total = await service.list_for_user(
        vehicle_id, user, statuses=None, severity=None, page=1, page_size=10
    )
    assert total == 2
    assert [a.severity for a in alerts] == ["critical", "warning"]

    criticals, ctotal = await service.list_for_user(
        vehicle_id, user, statuses=None, severity="critical", page=1, page_size=10
    )
    assert ctotal == 1
    assert criticals[0].rule_id == "COOLANT_TEMP_HIGH"

    opened, ototal = await service.list_for_user(
        vehicle_id, user, statuses=[ALERT_STATUS_OPEN], severity=None, page=1, page_size=10
    )
    assert ototal == 2

    resolved, rtotal = await service.list_for_user(
        vehicle_id, user, statuses=[ALERT_STATUS_RESOLVED], severity=None, page=1, page_size=10
    )
    assert rtotal == 0
    assert resolved == []
