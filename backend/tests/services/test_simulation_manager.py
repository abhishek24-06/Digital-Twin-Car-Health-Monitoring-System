"""Unit tests for the SimulationManager: lifecycle, conflict rules, crash
detection, stale cleanup and shutdown. A FakeProcessRunner drives the manager
entirely in-memory (no OS subprocesses)."""

import asyncio
import itertools
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.services.simulation_manager import (
    SimulationManager,
    _exit_reason,
    _kill_pid,
    _pid_alive,
)

SCENARIOS = ["normal", "high_temperature", "low_battery", "high_engine_load"]


class FakeProcess:
    _ids = itertools.count(1000)

    def __init__(self, *, slow_terminate: bool = False) -> None:
        self.pid = next(self._ids)
        self.terminated = False
        self.killed = False
        self.slow_terminate = slow_terminate
        self._completed_rc: int | None = None
        self._event = asyncio.Event()

    def poll(self) -> int | None:
        if self._completed_rc is not None:
            return self._completed_rc
        if self.terminated or self.killed:
            return -1
        return None

    async def wait(self) -> int:
        if self._completed_rc is None and not self._event.is_set():
            await self._event.wait()
        return self._completed_rc if self._completed_rc is not None else -1

    def terminate(self) -> None:
        self.terminated = True
        if not self.slow_terminate:
            self._event.set()

    def kill(self) -> None:
        self.killed = True
        self._event.set()

    def complete(self, rc: int = 0) -> None:
        self._completed_rc = rc
        self._event.set()


class FakeProcessRunner:
    def __init__(self) -> None:
        self.spawned: list[tuple[list[str], dict[str, str], Path]] = []
        self.processes: list[FakeProcess] = []

    def spawn(
        self,
        *,
        cmd: list[str],
        env: dict[str, str],
        cwd: Path,
        log_file: Path | None = None,
    ) -> FakeProcess:
        self.spawned.append((cmd, env, cwd))
        process = FakeProcess()
        self.processes.append(process)
        return process


@pytest.fixture
def manager(tmp_path: Path):
    settings = get_settings()
    runner = FakeProcessRunner()
    instance = SimulationManager(
        settings,
        runner,
        runtime_dir=tmp_path / "sims",
        grace_seconds=0.02,
        stop_timeout_seconds=0.05,
    )
    return instance, runner


async def _start(instance: SimulationManager, vehicle_id, scenario="normal") -> None:
    status = await instance.start(vehicle_id, scenario, 1.0, seed=7)
    assert status.status == "running", status


async def test_start_reaches_running(manager) -> None:
    instance, runner = manager
    vehicle_id = uuid4()
    status = await instance.start(vehicle_id, "high_temperature", 2.5, seed=99)
    assert status.status == "running"
    assert status.scenario == "high_temperature"
    assert status.interval_seconds == 2.5
    assert status.seed == 99
    assert status.started_at is not None
    assert status.error is None
    assert len(runner.processes) == 1
    cmd, env, cwd = runner.spawned[0]
    assert "-m" in cmd and "simulator.main" in cmd
    assert str(vehicle_id) == env["SIMULATOR_VEHICLE_ID"]
    assert env["SIMULATOR_SCENARIO"] == "high_temperature"
    assert env["SIMULATOR_INTERVAL_SECONDS"] == "2.5"
    assert cwd.is_dir()


async def test_start_default_seed(manager) -> None:
    instance, _ = manager
    status = await instance.start(uuid4(), "normal", 1.0)
    assert status.seed == 42


async def test_spawn_command_uses_single_real_interpreter(manager) -> None:
    """Regression for the Windows venv launcher double-spawn.

    CPython venvs on Windows ship a ``Scripts\\python.exe`` that re-spawns the
    base interpreter as a child and waits -- so launching the venv python
    creates one idle launcher plus one real worker per vehicle, and terminating
    the tracker orphans the worker. The manager must spawn the base
    interpreter directly and set ``__PYVENV_LAUNCHER__`` so exactly one process
    (the real worker) exists.
    """
    instance, runner = manager
    status = await instance.start(uuid4(), "normal", 1.0)
    assert status.status == "running"
    cmd, env, _ = runner.spawned[0]
    assert "-m" in cmd and "simulator.main" in cmd

    base = getattr(sys, "_base_executable", None)
    redirector_layout = (
        sys.platform == "win32"
        and base is not None
        and (Path(sys.executable).parent.parent / "pyvenv.cfg").exists()
    )
    if not redirector_layout:
        # No venv launcher to dodge (e.g. POSIX CI); any interpreter is fine.
        assert Path(cmd[0]).is_file()
        return
    assert Path(cmd[0]) == Path(base)
    assert env["__PYVENV_LAUNCHER__"] == sys.executable


async def test_duplicate_start_conflict(manager) -> None:
    instance, runner = manager
    vehicle_id = uuid4()
    await _start(instance, vehicle_id)
    with pytest.raises(ConflictError):
        await instance.start(vehicle_id, "normal", 1.0)
    assert len(runner.processes) == 1


async def test_start_after_error_allowed(manager) -> None:
    instance, runner = manager
    vehicle_id = uuid4()
    await _start(instance, vehicle_id)
    runner.processes[0].complete(2)
    status = await _wait_for_status(instance, vehicle_id, "error")
    assert status.status == "error"
    restarted = await instance.start(vehicle_id, "normal", 1.5)
    assert restarted.status == "running"
    assert restarted.interval_seconds == 1.5
    assert len(runner.processes) == 2


async def test_stop_is_idempotent_and_terminates(manager) -> None:
    instance, runner = manager
    vehicle_id = uuid4()
    await _start(instance, vehicle_id)
    stopped = await instance.stop(vehicle_id)
    assert stopped.status == "stopped"
    assert runner.processes[0].terminated
    again = await instance.stop(vehicle_id)
    assert again.status == "stopped"


async def test_stop_unstarted_vehicle_returns_stopped(manager) -> None:
    instance, _ = manager
    status = await instance.stop(uuid4())
    assert status.status == "stopped"
    assert status.scenario is None


async def test_get_status_unknown_vehicle_stopped(manager) -> None:
    instance, _ = manager
    status = await instance.get_status(uuid4())
    assert status.status == "stopped"
    assert status.error is None


async def test_crash_before_grace_marks_error(manager) -> None:
    instance, runner = manager
    vehicle_id = uuid4()
    task = asyncio.create_task(instance.start(vehicle_id, "low_battery", 1.0))
    await asyncio.sleep(0.01)
    runner.processes[-1].complete(3)
    status = await task
    assert status.status == "error"
    assert "exit code 3" in (status.error or "")


async def test_unexpected_exit_while_running_marks_error(manager) -> None:
    instance, runner = manager
    vehicle_id = uuid4()
    await _start(instance, vehicle_id)
    runner.processes[0].complete(0)
    status = await _wait_for_status(instance, vehicle_id, "error")
    assert status.status == "error"
    assert status.error == "Simulator process exited unexpectedly"
    assert list(instance._runtime_dir.glob("*.pid")) == []


async def test_restart_switches_scenario(manager) -> None:
    instance, runner = manager
    vehicle_id = uuid4()
    await _start(instance, vehicle_id, "normal")
    old = runner.processes[0]
    status = await instance.restart(vehicle_id, "high_engine_load", 3.0, seed=1)
    assert status.status == "running"
    assert status.scenario == "high_engine_load"
    assert old.terminated
    assert len(runner.processes) == 2
    assert not runner.processes[1].terminated


async def test_restart_without_existing(manager) -> None:
    instance, _ = manager
    status = await instance.restart(uuid4(), "normal", 1.0)
    assert status.status == "running"


async def test_statuses_for(manager) -> None:
    instance, _ = manager
    running_id = uuid4()
    await _start(instance, running_id)
    idle_id = uuid4()
    result = await instance.statuses_for([running_id, idle_id])
    assert result[running_id].status == "running"
    assert result[idle_id].status == "stopped"


async def test_shutdown_terminates_all(manager) -> None:
    instance, runner = manager
    a, b = uuid4(), uuid4()
    await _start(instance, a)
    await _start(instance, b)
    await instance.shutdown()
    assert all(p.terminated for p in runner.processes)
    assert instance._instances == {}
    await instance.shutdown()


async def test_cleanup_stale_kills_orphans(manager, monkeypatch) -> None:
    instance, _ = manager
    marker = instance._runtime_dir / f"{uuid4()}.99999.pid"
    marker.write_text("99999\n", encoding="ascii")

    killed: list[int] = []
    monkeypatch.setattr("app.services.simulation_manager._kill_pid", lambda pid: killed.append(pid))
    monkeypatch.setattr("app.services.simulation_manager._pid_alive", lambda pid: True)

    terminated = await instance.cleanup_stale()
    assert terminated == 1
    assert killed == [99999]
    assert not marker.exists()


async def test_cleanup_stale_skips_managed_instances(manager, monkeypatch) -> None:
    instance, runner = manager
    managed_id = uuid4()
    await _start(instance, managed_id)
    managed = runner.processes[0]
    own_marker = instance._runtime_dir / f"{managed_id}.{managed.pid}.pid"
    own_marker.write_text(f"{managed.pid}\n", encoding="ascii")

    killed: list[int] = []
    monkeypatch.setattr("app.services.simulation_manager._kill_pid", lambda pid: killed.append(pid))
    monkeypatch.setattr("app.services.simulation_manager._pid_alive", lambda pid: True)

    terminated = await instance.cleanup_stale()
    assert terminated == 0
    assert killed == []
    assert own_marker.exists()

    await instance.stop(managed_id)
    assert not own_marker.exists()


async def test_cleanup_stale_removes_dead_markers(manager, monkeypatch) -> None:
    instance, _ = manager
    marker = instance._runtime_dir / f"{uuid4()}.12345.pid"
    marker.write_text("12345\n", encoding="ascii")

    killed: list[int] = []
    monkeypatch.setattr("app.services.simulation_manager._kill_pid", lambda pid: killed.append(pid))
    monkeypatch.setattr("app.services.simulation_manager._pid_alive", lambda pid: False)

    terminated = await instance.cleanup_stale()
    assert terminated == 0
    assert killed == []
    assert not marker.exists()


async def test_cleanup_stale_skips_marker_owned_by_live_backend(manager, monkeypatch) -> None:
    instance, _ = manager
    live_owner = 555123
    marker = instance._runtime_dir / f"{uuid4()}.44444.pid"
    marker.write_text(f"44444\n{live_owner}\n", encoding="ascii")

    killed: list[int] = []
    monkeypatch.setattr("app.services.simulation_manager._kill_pid", lambda pid: killed.append(pid))
    monkeypatch.setattr("app.services.simulation_manager._pid_alive", lambda pid: True)

    terminated = await instance.cleanup_stale()
    assert terminated == 0
    assert killed == []
    assert marker.exists()


async def test_cleanup_stale_kills_marker_owned_by_dead_backend(manager, monkeypatch) -> None:
    instance, _ = manager
    dead_owner = 555124
    marker = instance._runtime_dir / f"{uuid4()}.44445.pid"
    marker.write_text(f"44445\n{dead_owner}\n", encoding="ascii")

    killed: list[int] = []
    monkeypatch.setattr("app.services.simulation_manager._kill_pid", lambda pid: killed.append(pid))

    def fake_alive(pid: int) -> bool:
        return pid != dead_owner

    monkeypatch.setattr(
        "app.services.simulation_manager._pid_alive",
        lambda pid: fake_alive(pid),
    )

    terminated = await instance.cleanup_stale()
    assert terminated == 1
    assert killed == [44445]
    assert not marker.exists()


async def test_terminate_escalates_to_kill(manager) -> None:
    instance, runner = manager
    vehicle_id = uuid4()
    task = asyncio.create_task(instance.start(vehicle_id, "normal", 1.0))
    await asyncio.sleep(0.01)
    process = runner.processes[-1]
    process.slow_terminate = True
    status = await task
    assert status.status == "running"
    await instance.stop(vehicle_id)
    assert process.killed


async def test_pid_helpers_never_raise() -> None:
    # 2**31 - 1 fits a 32-bit pid but never exists on a real system.
    invalid_pid = 2**31 - 1
    assert isinstance(_pid_alive(invalid_pid), bool)
    _kill_pid(invalid_pid)


def test_exit_reason_unknown_code_has_no_tail() -> None:
    reason = _exit_reason(7)
    assert "exit code 7" in reason
    assert "Last simulator output" not in reason


def test_exit_reason_appends_log_tail(tmp_path: Path) -> None:
    log_file = tmp_path / "vehicle.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
    reason = _exit_reason(7, log_file)
    assert "exit code 7" in reason
    assert "line 199" in reason
    assert "Last simulator output" in reason
    # Only the last _LOG_TAIL_LINES lines are kept.
    first_tail_line = reason.split("Last simulator output:\n")[1].splitlines()[0]
    assert int(first_tail_line.split()[-1]) == 200 - 40


def test_exit_reason_missing_log_is_graceful() -> None:
    reason = _exit_reason(7, Path("C:/definitely/missing/vehicle.log"))
    assert "exit code 7" in reason
    assert "Last simulator output" not in reason


def test_exit_reason_trims_very_long_logs(tmp_path: Path) -> None:
    log_file = tmp_path / "vehicle.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(500)), encoding="utf-8")
    reason = _exit_reason(1, log_file)
    assert "line 0" not in reason
    assert "line 499" in reason


async def _wait_for_status(instance: SimulationManager, vehicle_id, expected) -> object:
    for _ in range(100):
        status = await instance.get_status(vehicle_id)
        if status.status == expected:
            return status
        await asyncio.sleep(0.02)
    raise AssertionError(f"status never became {expected}: got {status.status}")
