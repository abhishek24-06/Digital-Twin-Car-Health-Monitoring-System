from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate
from app.schemas.vehicle import VehicleCreate
from app.services.health_monitor import (
    HealthMonitorService,
    MonitorPassResult,
    run_health_monitor_loop,
    should_escalate,
)
from app.services.telemetry_service import TelemetryService
from app.services.vehicle_health_service import VehicleHealthService
from app.services.vehicle_service import VehicleService
from tests.conftest import unique_vin


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession], clean_db) -> AsyncSession:
    async with session_factory() as s:
        yield s


@pytest.fixture
def monitor_settings() -> Settings:
    """Settings that make the monitor run immediately and unthrottled."""
    base = get_settings()
    return base.model_copy(
        update={
            "health_monitor_enabled": True,
            "health_monitor_min_seconds": 0.0,
            "health_monitor_max_vehicles": 25,
        }
    )


@pytest.fixture
def disabled_settings(monitor_settings: Settings) -> Settings:
    return monitor_settings.model_copy(update={"health_monitor_enabled": False})


class RecordingAgent:
    """Stand-in for AgentService that records escalations instead of calling an LLM."""

    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.error: Exception | None = None

    async def run_critical_event(self, vehicle_id, rule_ids=None, *, user=None):
        if self.error is not None:
            raise self.error
        self.calls.append(vehicle_id)
        return {"vehicle_id": vehicle_id}


async def _create_vehicle(session: AsyncSession) -> UUID:
    vehicle = await VehicleService(session, VehicleRepository(session)).create_vehicle(
        VehicleCreate(vin=unique_vin(), make="Toyota", model="Camry", year=2024)
    )
    # The monitor reads through fresh sessions, so seeded rows must be visible.
    await session.commit()
    return vehicle.id


def _payload(*, coolant: float, engine_load: float, ts: datetime) -> TelemetryCreate:
    return TelemetryCreate(
        timestamp=ts,
        rpm=2000.0,
        speed=60.0,
        engine_load=engine_load,
        coolant_temperature=coolant,
        oil_temperature=90.0,
        battery_voltage=13.5,
        fuel_level=60.0,
        intake_air_temperature=25.0,
        throttle_position=20.0,
        engine_runtime=1000.0,
        odometer=50000.0,
    )


async def _ingest(
    session: AsyncSession,
    vehicle_id: UUID,
    *,
    coolant: float = 90.0,
    engine_load: float = 30.0,
    count: int = 15,
    start_seconds_ago: int = 15,
) -> None:
    telemetry_service = TelemetryService(
        session=session,
        repository=TelemetryRepository(session),
        vehicle_repository=VehicleRepository(session),
    )
    now = datetime.now(UTC)
    for index in range(count):
        await telemetry_service.create_telemetry(
            vehicle_id,
            _payload(
                coolant=coolant,
                engine_load=engine_load,
                ts=now - timedelta(seconds=start_seconds_ago - index),
            ),
        )
    await session.commit()


def _health_factory(explode_for: UUID | None = None):
    """Build health services, optionally raising for one specific vehicle."""

    def factory(session: AsyncSession) -> VehicleHealthService:
        real = VehicleHealthService(
            session=session,
            vehicle_repository=VehicleRepository(session),
            telemetry_repository=TelemetryRepository(session),
            health_repository=HealthSnapshotRepository(session),
        )

        class Stub:
            async def analyze_vehicle(self, vehicle_id, **kwargs):
                if vehicle_id == explode_for:
                    raise RuntimeError("analysis failed")
                return await real.analyze_vehicle(vehicle_id, **kwargs)

        return Stub()

    return factory


async def test_run_pass_evaluates_due_vehicle_and_persists_snapshot(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monitor_settings: Settings,
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest(session, vehicle_id)
    agent = RecordingAgent()
    monitor = HealthMonitorService(
        session_factory,
        settings=monitor_settings,
        health_service_factory=_health_factory(),
        agent_service_factory=lambda _: agent,
    )

    result = await monitor.run_pass()

    assert result == MonitorPassResult(considered=1, evaluated=1, escalated=0, failed=0)
    snapshot = await HealthSnapshotRepository(session).get_latest_by_vehicle(vehicle_id)
    assert snapshot is not None
    assert snapshot.health_status == "healthy"
    assert agent.calls == []


async def test_run_pass_escalates_critical_health_to_the_agent(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monitor_settings: Settings,
) -> None:
    vehicle_id = await _create_vehicle(session)
    # Two critical findings (coolant > 110 and mean engine load > 60) drop the
    # score to 40, which classifies as "critical".
    await _ingest(session, vehicle_id, coolant=120.0, engine_load=90.0)
    agent = RecordingAgent()
    monitor = HealthMonitorService(
        session_factory,
        settings=monitor_settings,
        health_service_factory=_health_factory(),
        agent_service_factory=lambda _: agent,
    )

    result = await monitor.run_pass()

    assert result.escalated == 1
    assert result.failed == 0
    assert agent.calls == [vehicle_id]


async def test_run_pass_does_not_escalate_attention_health(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monitor_settings: Settings,
) -> None:
    vehicle_id = await _create_vehicle(session)
    # A single critical finding scores 70, which classifies as "attention".
    await _ingest(session, vehicle_id, coolant=120.0)
    agent = RecordingAgent()
    monitor = HealthMonitorService(
        session_factory,
        settings=monitor_settings,
        health_service_factory=_health_factory(),
        agent_service_factory=lambda _: agent,
    )

    result = await monitor.run_pass()

    assert result.evaluated == 1
    assert result.escalated == 0
    assert agent.calls == []


async def test_disabled_monitor_does_nothing(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    disabled_settings: Settings,
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest(session, vehicle_id)
    agent = RecordingAgent()
    monitor = HealthMonitorService(
        session_factory,
        settings=disabled_settings,
        health_service_factory=_health_factory(),
        agent_service_factory=lambda _: agent,
    )

    result = await monitor.run_pass()

    assert result == MonitorPassResult()
    snapshot = await HealthSnapshotRepository(session).get_latest_by_vehicle(vehicle_id)
    assert snapshot is None
    assert agent.calls == []


async def test_second_pass_is_a_no_op_without_new_telemetry(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monitor_settings: Settings,
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest(session, vehicle_id)
    monitor = HealthMonitorService(
        session_factory,
        settings=monitor_settings,
        health_service_factory=_health_factory(),
        agent_service_factory=lambda _: RecordingAgent(),
    )

    first = await monitor.run_pass()
    second = await monitor.run_pass()

    assert first.evaluated == 1
    assert second == MonitorPassResult()


async def test_min_seconds_throttles_recently_evaluated_vehicle(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monitor_settings: Settings,
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest(session, vehicle_id)
    unthrottled = HealthMonitorService(
        session_factory,
        settings=monitor_settings,
        health_service_factory=_health_factory(),
        agent_service_factory=lambda _: RecordingAgent(),
    )
    await unthrottled.run_pass()
    await _ingest(session, vehicle_id, count=1, start_seconds_ago=0)

    throttled = HealthMonitorService(
        session_factory,
        settings=monitor_settings.model_copy(update={"health_monitor_min_seconds": 3600.0}),
        health_service_factory=_health_factory(),
        agent_service_factory=lambda _: RecordingAgent(),
    )

    assert await throttled.run_pass() == MonitorPassResult()
    assert (await unthrottled.run_pass()).evaluated == 1


async def test_evaluation_failure_is_isolated(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monitor_settings: Settings,
) -> None:
    healthy_id = await _create_vehicle(session)
    broken_id = await _create_vehicle(session)
    await _ingest(session, healthy_id)
    await _ingest(session, broken_id)
    monitor = HealthMonitorService(
        session_factory,
        settings=monitor_settings,
        health_service_factory=_health_factory(explode_for=broken_id),
        agent_service_factory=lambda _: RecordingAgent(),
    )

    result = await monitor.run_pass()

    assert result.considered == 2
    assert result.evaluated == 1
    assert result.failed == 1
    assert len(result.errors) == 1
    assert str(broken_id) in result.errors[0]
    assert await HealthSnapshotRepository(session).get_latest_by_vehicle(healthy_id) is not None


async def test_escalation_failure_is_isolated(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monitor_settings: Settings,
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest(session, vehicle_id, coolant=120.0, engine_load=90.0)
    agent = RecordingAgent()
    agent.error = RuntimeError("agent unavailable")
    monitor = HealthMonitorService(
        session_factory,
        settings=monitor_settings,
        health_service_factory=_health_factory(),
        agent_service_factory=lambda _: agent,
    )

    result = await monitor.run_pass()

    assert result.evaluated == 1
    assert result.escalated == 0
    assert result.failed == 1
    assert "agent unavailable" in result.errors[0]


@pytest.mark.parametrize(
    ("health_status", "expected"),
    [
        ("critical", True),
        ("attention", False),
        ("healthy", False),
        ("unknown", False),
        ("no_data", False),
        ("limited_data", False),
    ],
)
def test_should_escalate_only_critical(health_status: str, expected: bool) -> None:
    assert should_escalate(health_status) is expected


async def _run_loop_until_cancelled(monitor, interval_seconds: float, duration: float) -> int:
    task = asyncio.create_task(run_health_monitor_loop(monitor, interval_seconds=interval_seconds))
    await asyncio.sleep(duration)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return monitor.calls


class StubMonitor:
    def __init__(self, failures: int = 0) -> None:
        self.calls = 0
        self.failures = failures

    async def run_pass(self) -> MonitorPassResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("database is unreachable")
        return MonitorPassResult()


async def test_loop_runs_the_monitor_on_the_given_interval() -> None:
    monitor = StubMonitor()

    calls = await _run_loop_until_cancelled(monitor, interval_seconds=0.01, duration=0.2)

    assert calls >= 1


async def test_loop_survives_a_pass_that_fails_entirely(caplog) -> None:
    monitor = StubMonitor(failures=1)

    with caplog.at_level(logging.ERROR):
        calls = await _run_loop_until_cancelled(monitor, interval_seconds=0.01, duration=0.3)

    assert calls >= 2, "the loop died instead of retrying on the next tick"
    assert any("health monitor pass failed" in message for message in caplog.messages)


async def test_start_health_monitor_is_a_no_op_when_disabled() -> None:
    # conftest pins HEALTH_MONITOR_ENABLED=false for the whole suite.
    import app.main as main_module

    assert main_module._start_health_monitor() is None


async def test_start_health_monitor_creates_a_cancellable_task(
    monkeypatch, monitor_settings: Settings
) -> None:
    import app.main as main_module

    # A long interval means the task never runs a pass during this test.
    enabled = monitor_settings.model_copy(update={"health_monitor_interval_seconds": 3600.0})
    monkeypatch.setattr(main_module, "settings", enabled)

    task = main_module._start_health_monitor()

    assert task is not None
    assert task.get_name() == "health-monitor"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
