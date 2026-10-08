"""End-to-end: SimulationManager spawns a real simulator subprocess which
publishes live telemetry through the MQTT broker to the real subscriber and
into PostgreSQL.

Marked ``mqtt_e2e`` so the default suite excludes it; run with ``pytest -m
mqtt_e2e`` (or ``make mqtt-test``) with a broker reachable on the configured
host/port. When no broker is reachable the test skips instead of failing.

This exercises the feature's true production path: the manager builds the
simulator environment from validated request fields, spawns ``python -m
simulator.main`` as its own process, and the subscriber's telemetry ingestion
picks the simulated vehicle's frames up from the database.
"""

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.telemetry import TelemetryRecord
from app.mqtt.subscriber import MQTTSubscriber
from app.services.simulation_manager import SimulationManager
from app.services.subscriber_manager import SubscriberSupervisor

pytestmark = pytest.mark.mqtt_e2e


def _broker_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


async def _wait_for_records(session_factory, vehicle_id: str, timeout: float = 30.0) -> bool:
    async def _count() -> int:
        async with session_factory() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(TelemetryRecord)
                .where(TelemetryRecord.vehicle_id == vehicle_id)
            )
        return int(total or 0)

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await _count() >= 1:
            return True
        await asyncio.sleep(0.2)
    return False


async def _run_case(session_factory, sample_vehicle, runtime_dir: Path) -> None:
    settings = Settings()
    vehicle_id = sample_vehicle["id"]
    manager = SimulationManager(
        settings,
        runtime_dir=runtime_dir,
        grace_seconds=1.0,
        stop_timeout_seconds=3.0,
    )
    subscriber = MQTTSubscriber(settings, session_factory)
    stop_event = asyncio.Event()

    try:
        status = await manager.start(vehicle_id, "normal", 0.5, seed=1)
        assert status.status == "running", status
        assert status.interval_seconds == 0.5

        task = asyncio.create_task(subscriber.run_forever(stop_event))
        try:
            persisted = await _wait_for_records(session_factory, vehicle_id)
            assert persisted, "spawned simulator never produced a stored telemetry record"
        finally:
            stop_event.set()
            await asyncio.wait_for(task, timeout=10.0)

        async with session_factory() as session:
            record = await session.scalar(
                select(TelemetryRecord)
                .where(TelemetryRecord.vehicle_id == vehicle_id)
                .order_by(TelemetryRecord.timestamp.desc())
            )
        assert record is not None
        assert datetime.now(UTC) - record.created_at < timedelta(seconds=60)

        stopped = await manager.stop(vehicle_id)
        assert stopped.status == "stopped", stopped
        live = await manager.get_status(vehicle_id)
        assert live.status == "stopped"
        assert live.error is None
    finally:
        await manager.shutdown()
        assert list(runtime_dir.glob("*.pid")) == []


def test_spawned_simulator_streams_to_postgres(session_factory, sample_vehicle, tmp_path) -> None:
    settings = Settings()
    if not _broker_reachable(settings.mqtt_broker_host, settings.mqtt_broker_port):
        pytest.skip(f"no MQTT broker at {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")

    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(
            _run_case(session_factory, sample_vehicle, tmp_path / "sim-runtime")
        )
    finally:
        loop.close()


def _module_process_pids(module: str) -> set[int]:
    """PIDs of ``python -m <module>`` processes running on this machine."""
    found: set[int] = set()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"] or []
        except (psutil.Error, OSError):
            continue
        if "-m" in cmdline and module in cmdline:
            found.add(proc.info["pid"])
    return found


async def _run_supervised_case(session_factory, sample_vehicle, runtime_dir: Path) -> None:
    settings = Settings()
    vehicle_id = sample_vehicle["id"]
    manager = SimulationManager(
        settings,
        runtime_dir=runtime_dir,
        grace_seconds=1.0,
        stop_timeout_seconds=3.0,
    )
    supervisor = SubscriberSupervisor(
        settings,
        runtime_dir=runtime_dir,
        stop_timeout_seconds=3.0,
        auto_restart=False,
    )
    sims_before = _module_process_pids("simulator.main")
    subs_before = _module_process_pids("app.mqtt.subscriber")

    try:
        health = await supervisor.ensure_running()
        assert health.running, "supervisor failed to start the subscriber"
        subs_after = _module_process_pids("app.mqtt.subscriber") - subs_before
        assert len(subs_after) == 1, (
            f"expected exactly one new subscriber process, got {sorted(subs_after)}"
        )

        status = await manager.start(vehicle_id, "normal", 0.5, seed=1)
        assert status.status == "running", status
        sims_after = _module_process_pids("simulator.main") - sims_before
        assert len(sims_after) == 1, (
            f"expected exactly ONE simulator process per start, got {sorted(sims_after)} "
            "(a Windows venv launcher double-spawn would create two)"
        )

        persisted = await _wait_for_records(session_factory, vehicle_id)
        assert persisted, "supervised subscriber never stored a telemetry record"

        stopped = await manager.stop(vehicle_id)
        assert stopped.status == "stopped", stopped
        # The supervised process must actually die: no orphaned simulator left
        # behind after the launcher fix.
        deadline = asyncio.get_event_loop().time() + 6.0
        while asyncio.get_event_loop().time() < deadline:
            if not (_module_process_pids("simulator.main") & set(sims_after)):
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("stopped simulator process is still alive (orphaned)")

        await supervisor.restart()
        assert (await supervisor.health()).running
    finally:
        await supervisor.shutdown()
        await manager.shutdown()
        assert list(runtime_dir.glob("*.pid")) == []


def test_supervised_subscriber_streams_and_never_duplicates_processes(
    session_factory, sample_vehicle, tmp_path
) -> None:
    """The backend-owned subscriber ingests telemetry end-to-end, each start
    yields exactly one simulator process (no venv launcher double-spawn), and
    stopping leaves no orphan."""
    settings = Settings()
    if not _broker_reachable(settings.mqtt_broker_host, settings.mqtt_broker_port):
        pytest.skip(f"no MQTT broker at {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")

    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(
            _run_supervised_case(session_factory, sample_vehicle, tmp_path / "supervised-runtime")
        )
    finally:
        loop.close()
