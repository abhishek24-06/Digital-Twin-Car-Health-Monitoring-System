"""Unit tests for the backend-owned MQTT subscriber supervisor.

The supervisor is the piece that makes "running" honest: it owns the
``python -m app.mqtt.subscriber`` process, restarts it on unexpected exit, and
exposes its health so the simulation routes can downgrade a vehicle to
``degraded`` while ingestion is offline. A FakeProcessRunner drives it entirely
in-memory (no OS subprocesses)."""

import asyncio
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.services.subscriber_manager import SubscriberSupervisor, _read_marker_pid
from tests.services.test_simulation_manager import FakeProcessRunner


def _make(
    tmp_path: Path, *, auto_restart: bool = True
) -> tuple[SubscriberSupervisor, FakeProcessRunner]:
    settings = get_settings()
    runner = FakeProcessRunner()
    supervisor = SubscriberSupervisor(
        settings,
        runner,
        runtime_dir=tmp_path / "subs",
        stop_timeout_seconds=0.05,
        auto_restart=auto_restart,
    )
    return supervisor, runner


async def _wait_for(predicate, timeout: float = 8.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true")


async def test_ensure_running_spawns_exactly_one_subscriber(tmp_path: Path) -> None:
    supervisor, runner = _make(tmp_path)
    health = await supervisor.ensure_running()
    assert health.running
    assert health.started_at is not None
    assert health.last_error is None

    assert len(runner.spawned) == 1
    cmd, env, cwd = runner.spawned[0]
    assert "-m" in cmd and "app.mqtt.subscriber" in cmd
    assert cwd.is_dir()
    assert "MQTT_BROKER_HOST" in env

    marker = supervisor._pid_file
    assert marker.exists()
    owner_pid = marker.read_text(encoding="ascii").splitlines()[-1]
    assert owner_pid.strip().isdigit()
    await supervisor.shutdown()
    assert not marker.exists()


async def test_ensure_running_is_idempotent(tmp_path: Path) -> None:
    supervisor, runner = _make(tmp_path)
    await supervisor.ensure_running()
    await supervisor.ensure_running()
    assert len(runner.spawned) == 1
    await supervisor.shutdown()


async def test_unexpected_exit_restarts_and_records_error(tmp_path: Path) -> None:
    supervisor, runner = _make(tmp_path)
    await supervisor.ensure_running()
    runner.processes[0].complete(2)

    await _wait_for(lambda: len(runner.spawned) >= 2)
    health = await supervisor.health()
    assert health.running
    assert health.restarts == 1
    # A successful respawn clears the transient failure; the earlier crash is
    # observable through restarts and the exit-reason on the log.
    assert health.last_error is None
    await supervisor.shutdown()


async def test_no_auto_restart_leaves_stopped_health(tmp_path: Path) -> None:
    supervisor, runner = _make(tmp_path, auto_restart=False)
    await supervisor.ensure_running()
    runner.processes[0].complete(0)

    await _wait_for(lambda: runner.processes[0]._completed_rc is not None)
    await asyncio.sleep(0.05)
    health = await supervisor.health()
    assert not health.running
    assert health.restarts == 0
    assert health.last_error is not None
    assert not supervisor._pid_file.exists()
    await supervisor.shutdown()


async def test_restart_stops_then_starts_fresh(tmp_path: Path) -> None:
    supervisor, runner = _make(tmp_path)
    await supervisor.ensure_running()
    first = runner.processes[0]
    before = await supervisor.health()
    assert before.running

    health = await supervisor.restart()
    assert health.running
    assert runner.processes[0].terminated or first.terminated
    assert len(runner.spawned) == 2
    await supervisor.shutdown()


async def test_shutdown_terminates_and_is_idempotent(tmp_path: Path) -> None:
    supervisor, runner = _make(tmp_path)
    await supervisor.ensure_running()
    process = runner.processes[0]

    await supervisor.shutdown()
    assert process.terminated
    assert not (await supervisor.health()).running
    await supervisor.shutdown()


async def test_reclaim_orphan_kills_dead_owner_marker(tmp_path: Path, monkeypatch) -> None:
    supervisor, runner = _make(tmp_path)
    marker = supervisor._pid_file
    marker.write_text("99999\n555120\n", encoding="ascii")

    killed: list[int] = []
    monkeypatch.setattr("app.services.subscriber_manager._kill_pid", lambda pid: killed.append(pid))
    dead = {555120}
    monkeypatch.setattr("app.services.subscriber_manager._pid_alive", lambda pid: pid not in dead)

    await supervisor.ensure_running()
    assert killed == [99999]
    # The orphan marker is reclaimed and replaced by the fresh spawn's marker.
    assert _read_marker_pid(supervisor._pid_file) == runner.processes[0].pid
    await supervisor.shutdown()


async def test_reclaim_orphan_skips_live_owner_marker(tmp_path: Path, monkeypatch) -> None:
    supervisor, runner = _make(tmp_path)
    marker = supervisor._pid_file
    marker.write_text("99999\n555121\n", encoding="ascii")

    killed: list[int] = []
    monkeypatch.setattr("app.services.subscriber_manager._kill_pid", lambda pid: killed.append(pid))
    monkeypatch.setattr("app.services.subscriber_manager._pid_alive", lambda pid: True)

    await supervisor.ensure_running()
    assert killed == []
    assert marker.exists()
    await supervisor.shutdown()


async def test_read_marker_pid_helper() -> None:
    tmp = Path(__import__("tempfile").gettempdir())
    marker = tmp / f"read-marker-{uuid4().hex}.pid"
    marker.write_text("4242\n88\n", encoding="ascii")
    try:
        assert _read_marker_pid(marker) == 4242
    finally:
        marker.unlink(missing_ok=True)
