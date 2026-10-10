"""Dynamic per-vehicle simulator process management.

The backend spawns and supervises one ``simulator.main`` subprocess per
vehicle from the Simulation Control API. This module owns that lifecycle:
start/stop/restart/status, duplicate-start protection, unexpected-termination
detection, stale-process cleanup after a backend restart, and graceful
shutdown.

Design notes
------------
* Processes are spawned with ``subprocess.Popen`` and waited on through
  ``asyncio.to_thread`` so the manager works on both the Proactor event loop
  uvicorn uses on Windows and the selector loops used in tests. Nothing here
  assumes POSIX.
* One process per simulator: ``python_module_command()`` resolves the real
  interpreter so the spawn never goes through the Windows venv launcher
  (which would create an idle parent + a real worker and orphan the worker on
  stop); the child always boots against the venv via ``__PYVENV_LAUNCHER__``.
* ``SIMULATOR_VEHICLE_ID`` is required by the simulator (no default), so the
  manager always supplies it; every other ``SIMULATOR_*``/``MQTT_*`` value is
  derived from validated request fields and ``Settings``. User input reaches
  the environment only through the validated ``SimulationStartRequest``
  fields -- never as arbitrary environment variables.
* PID markers: each spawn writes ``{runtime_dir}/{vehicle_id}.{pid}.pid``.
  Markers are removed when the supervised process exits. If the backend
  restarts while simulators are still running, the markers survive and let
  ``cleanup_stale()`` terminate the orphans. Using a pid-suffixed filename
  means an old supervisor can never delete a freshly spawned marker for the
  same vehicle (e.g. mid-restart).
* Output capture: each spawn writes the simulator's stdout+stderr to
  ``{runtime_dir}/{vehicle_id}.log`` instead of ``DEVNULL``. When a process
  exits unexpectedly the last lines are folded into the error reason, so a
  crash that would otherwise be a bare exit code leaves an observable trail.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import signal
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, SimulationError
from app.schemas.simulation import SimulationState
from app.schemas.workflow import (
    WorkflowStage,
    WorkflowStatus,
    WorkflowType,
    new_correlation_id,
    sanitize_metadata,
)
from app.services.workflow_event_bus import publish_workflow_event
from simulator.config import ScenarioName

logger = logging.getLogger(__name__)

# Working directory the simulator child runs in: ``python -m simulator.main``
# resolves against the backend package layout and loads the same ``.env``.
BACKEND_DIR = Path(__file__).resolve().parents[2]

DEFAULT_SEED = 42

_STATE_STOPPED: SimulationState = "stopped"
_STATE_STARTING: SimulationState = "starting"
_STATE_RUNNING: SimulationState = "running"
_STATE_STOPPING: SimulationState = "stopping"
_STATE_ERROR: SimulationState = "error"

_PID_SUFFIX = ".pid"
_WIN_WAIT_TIMEOUT = 0x00000102  # WAIT_TIMEOUT -> process still running
_WIN_ERROR_INVALID_PARAMETER = 87


class ProcessHandle(Protocol):
    """The subset of ``subprocess.Popen`` the manager depends on."""

    pid: int

    def poll(self) -> int | None: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class ProcessRunner(Protocol):
    """Factory abstraction so tests can drive the manager without OS processes."""

    def spawn(
        self,
        *,
        cmd: list[str],
        env: dict[str, str],
        cwd: Path,
        log_file: Path | None = None,
    ) -> ProcessHandle: ...


class RealProcess:
    """Adapter around ``subprocess.Popen`` used in production."""

    def __init__(self, popen: subprocess.Popen[str]) -> None:
        self._popen = popen

    @property
    def pid(self) -> int:
        return self._popen.pid

    def poll(self) -> int | None:
        return self._popen.poll()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._popen.wait)

    def terminate(self) -> None:
        # POSIX: SIGTERM lets the simulator announce its offline status and
        # exit cleanly. Windows: ``Popen.terminate()`` is TerminateProcess, an
        # immediate stop -- acceptable, an offline announcement is not a
        # correctness requirement (telemetry simply stops).
        self._popen.terminate()

    def kill(self) -> None:
        self._popen.kill()


class RealProcessRunner:
    """Spawns real simulator subprocesses on this machine."""

    def spawn(
        self,
        *,
        cmd: list[str],
        env: dict[str, str],
        cwd: Path,
        log_file: Path | None = None,
    ) -> ProcessHandle:
        kwargs: dict[str, object] = {
            "cwd": str(cwd),
            "env": env,
            "text": True,
        }
        if log_file is not None:
            # Keep stdout and stderr so unexpected exits leave an observable
            # trail; the manager folds the last lines into the error reason.
            handle = open(log_file, "w", encoding="utf-8")
            kwargs["stdout"] = handle
            kwargs["stderr"] = subprocess.STDOUT
        else:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        if sys.platform == "win32":
            # Give the child its own process group so termination handling is
            # deterministic and console events stay isolated.
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        popen = subprocess.Popen(cmd, **kwargs)
        if log_file is not None:
            handle.close()
        return RealProcess(popen)


@dataclass(frozen=True)
class SimulationStatus:
    """Process-state snapshot exposed to the API layer (no PID/environment)."""

    vehicle_id: UUID
    status: SimulationState
    scenario: ScenarioName | None = None
    interval_seconds: float | None = None
    seed: int | None = None
    started_at: datetime | None = None
    error: str | None = None
    correlation_id: str | None = None


@dataclass
class _Instance:
    vehicle_id: UUID
    scenario: ScenarioName
    interval_seconds: float
    seed: int
    status: SimulationState
    process: ProcessHandle | None
    pid_file: Path
    started_at: datetime
    error: str | None = None
    log_file: Path | None = None
    settled: asyncio.Event = field(default_factory=asyncio.Event)
    monitor_task: asyncio.Task[None] | None = None


class SimulationManager:
    """Supervises one simulator subprocess per vehicle."""

    def __init__(
        self,
        settings: Settings,
        runner: ProcessRunner | None = None,
        *,
        runtime_dir: Path | None = None,
        grace_seconds: float | None = None,
        stop_timeout_seconds: float | None = None,
    ) -> None:
        self._settings = settings
        self._runner = runner if runner is not None else RealProcessRunner()
        self._runtime_dir = (
            runtime_dir if runtime_dir is not None else Path(settings.simulation_runtime_dir)
        )
        self._grace_seconds = (
            grace_seconds
            if grace_seconds is not None
            else settings.simulation_startup_grace_seconds
        )
        self._stop_timeout = (
            stop_timeout_seconds
            if stop_timeout_seconds is not None
            else settings.simulation_stop_timeout_seconds
        )
        try:
            self._runtime_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Cannot create simulation marker dir %s", self._runtime_dir)
        self._instances: dict[UUID, _Instance] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Public control surface                                            #
    # ------------------------------------------------------------------ #

    async def start(
        self,
        vehicle_id: UUID,
        scenario: ScenarioName,
        interval_seconds: float,
        seed: int | None = None,
        *,
        correlation_id: str | None = None,
    ) -> SimulationStatus:
        """Spawn and supervise a simulator for ``vehicle_id``.

        Raises ``ConflictError`` when a simulator is already running/starting/
        stopping for the vehicle, and ``SimulationError`` when the process
        cannot be spawned at the OS level.
        """
        if correlation_id is None:
            correlation_id = new_correlation_id("sim")

        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_START_REQUESTED,
            status=WorkflowStatus.STARTED,
            message=f"Simulation start requested for vehicle {vehicle_id}",
            vehicle_id=str(vehicle_id),
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "scenario": scenario,
                    "interval_seconds": interval_seconds,
                    "seed": seed or DEFAULT_SEED,
                }
            ),
        )

        async with self._lock:
            existing = self._instances.get(vehicle_id)
            if existing is not None and existing.status not in (
                _STATE_STOPPED,
                _STATE_ERROR,
            ):
                raise ConflictError("A simulation is already running for this vehicle")
            instance = await self._spawn_locked(vehicle_id, scenario, interval_seconds, seed)

        await self._await_initial_state(instance)

        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_STARTED,
            status=WorkflowStatus.SUCCESS,
            message=f"Simulation started for vehicle {vehicle_id}",
            vehicle_id=str(vehicle_id),
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "scenario": scenario,
                    "interval_seconds": interval_seconds,
                    "pid": instance.process.pid if instance.process else None,
                }
            ),
        )

        return replace(self._to_status(vehicle_id, instance), correlation_id=correlation_id)

    async def stop(
        self, vehicle_id: UUID, *, correlation_id: str | None = None
    ) -> SimulationStatus:
        """Gracefully stop any simulator for ``vehicle_id``.

        Idempotent: stopping a vehicle with no simulator returns a ``stopped``
        status instead of an error.
        """
        if correlation_id is None:
            correlation_id = new_correlation_id("sim")

        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_STOP_REQUESTED,
            status=WorkflowStatus.STARTED,
            message=f"Simulation stop requested for vehicle {vehicle_id}",
            vehicle_id=str(vehicle_id),
            correlation_id=correlation_id,
        )

        async with self._lock:
            instance = self._instances.get(vehicle_id)
            process = instance.process if instance is not None else None
            if process is None:
                await publish_workflow_event(
                    workflow=WorkflowType.SIMULATION,
                    stage=WorkflowStage.SIMULATION_STOPPED,
                    status=WorkflowStatus.SUCCESS,
                    message=f"Simulation stop requested but no simulator running for vehicle {vehicle_id}",
                    vehicle_id=str(vehicle_id),
                    correlation_id=correlation_id,
                )
                return replace(self._stopped_status(vehicle_id), correlation_id=correlation_id)
            if instance.status not in (_STATE_RUNNING, _STATE_STARTING, _STATE_STOPPING):
                return replace(self._to_status(vehicle_id, instance), correlation_id=correlation_id)
            instance.status = _STATE_STOPPING
            try:
                await self._terminate(process)
            finally:
                self._remove_pid_file(instance)
                if self._instances.get(vehicle_id) is instance:
                    # Stop is authoritative even if the supervisor has not
                    # observed the exit yet; the response must not race it.
                    instance.status = _STATE_STOPPED
                    instance.error = None

        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_STOPPED,
            status=WorkflowStatus.SUCCESS,
            message=f"Simulation stopped for vehicle {vehicle_id}",
            vehicle_id=str(vehicle_id),
            correlation_id=correlation_id,
        )

        return replace(self._to_status(vehicle_id, instance), correlation_id=correlation_id)

    async def restart(
        self,
        vehicle_id: UUID,
        scenario: ScenarioName,
        interval_seconds: float,
        seed: int | None = None,
        *,
        correlation_id: str | None = None,
    ) -> SimulationStatus:
        """Stop any running simulator and start a fresh one with new config."""
        if correlation_id is None:
            correlation_id = new_correlation_id("sim")

        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_RESTART_REQUESTED,
            status=WorkflowStatus.STARTED,
            message=f"Simulation restart requested for vehicle {vehicle_id}",
            vehicle_id=str(vehicle_id),
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "scenario": scenario,
                    "interval_seconds": interval_seconds,
                    "seed": seed or DEFAULT_SEED,
                }
            ),
        )

        async with self._lock:
            existing = self._instances.get(vehicle_id)
            if (
                existing is not None
                and existing.process is not None
                and existing.status
                in (
                    _STATE_RUNNING,
                    _STATE_STARTING,
                    _STATE_STOPPING,
                )
            ):
                existing.status = _STATE_STOPPING
                await self._terminate(existing.process)
                self._remove_pid_file(existing)
            instance = await self._spawn_locked(vehicle_id, scenario, interval_seconds, seed)
        await self._await_initial_state(instance)

        await publish_workflow_event(
            workflow=WorkflowType.SIMULATION,
            stage=WorkflowStage.SIMULATION_RESTARTED,
            status=WorkflowStatus.SUCCESS,
            message=f"Simulation restarted for vehicle {vehicle_id}",
            vehicle_id=str(vehicle_id),
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "scenario": scenario,
                    "interval_seconds": interval_seconds,
                    "pid": instance.process.pid if instance.process else None,
                }
            ),
        )

        return replace(self._to_status(vehicle_id, instance), correlation_id=correlation_id)

    async def get_status(self, vehicle_id: UUID) -> SimulationStatus:
        async with self._lock:
            return self._to_status(vehicle_id, self._instances.get(vehicle_id))

    async def statuses_for(self, vehicle_ids: list[UUID]) -> dict[UUID, SimulationStatus]:
        """Status snapshot for many vehicles in one locked pass."""
        async with self._lock:
            return {vid: self._to_status(vid, self._instances.get(vid)) for vid in vehicle_ids}

    async def cleanup_stale(self) -> int:
        """Terminate simulator processes left over from a previous backend run.

        Reads the PID markers directory and kills any live process recorded
        there that is not managed by this instance. Returns how many processes
        were terminated. Safe to run repeatedly.

        Markers are owner-tagged: the second line of each marker file holds the
        PID of the backend process that spawned the simulator. A marker whose
        owner is a *live* process is intentionally skipped -- that owner is a
        different, active backend instance sharing this machine's marker
        directory, and its simulators must not be torn down as if they were
        orphans. Only markers owned by a dead process (or owned by this very
        process) are eligible for termination.
        """
        try:
            markers = list(self._runtime_dir.glob(f"*{_PID_SUFFIX}"))
        except OSError:
            logger.warning("Cannot scan simulation marker dir %s", self._runtime_dir)
            return 0
        terminated = 0
        for marker in markers:
            parts = marker.name.split(".")
            if len(parts) != 3:
                continue
            try:
                vehicle_id = UUID(parts[0])
                pid = int(parts[1])
            except ValueError:
                continue
            if vehicle_id in self._instances:
                continue
            owner_pid = _read_marker_owner(marker)
            if owner_pid is not None and owner_pid != os.getpid() and _pid_alive(owner_pid):
                # Another live backend instance owns this simulator; not an orphan.
                continue
            if _pid_alive(pid):
                logger.warning(
                    "Terminating orphaned simulator pid=%s (vehicle %s, owner=%s)",
                    pid,
                    vehicle_id,
                    owner_pid,
                )
                _kill_pid(pid)
                terminated += 1
            marker.unlink(missing_ok=True)
        return terminated

    async def shutdown(self) -> None:
        """Terminate every supervised simulator and stop its watcher. Idempotent."""
        instances = list(self._instances.values())
        live = [
            inst for inst in instances if inst.process is not None and inst.status != _STATE_STOPPED
        ]
        for inst in live:
            inst.status = _STATE_STOPPING
        for inst in live:
            await self._terminate(inst.process)
            self._remove_pid_file(inst)
        self._instances.clear()
        tasks = [inst.monitor_task for inst in instances if inst.monitor_task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    async def _spawn_locked(
        self,
        vehicle_id: UUID,
        scenario: ScenarioName,
        interval_seconds: float,
        seed: int | None,
    ) -> _Instance:
        seed_value = DEFAULT_SEED if seed is None else int(seed)
        cmd, env = self._build_command_and_env(vehicle_id, scenario, interval_seconds, seed_value)
        log_file = self._runtime_dir / f"{vehicle_id}.log"
        process = await self._spawn(cmd, env, log_file)
        instance = _Instance(
            vehicle_id=vehicle_id,
            scenario=scenario,
            interval_seconds=interval_seconds,
            seed=seed_value,
            status=_STATE_STARTING,
            process=process,
            pid_file=self._runtime_dir / f"{vehicle_id}.{process.pid}.pid",
            started_at=datetime.now(UTC),
            log_file=log_file,
        )
        self._write_pid_file(instance.pid_file, process.pid, owner_pid=os.getpid())
        self._instances[vehicle_id] = instance
        instance.monitor_task = asyncio.create_task(
            self._supervise(instance), name=f"simulator-{vehicle_id}"
        )
        return instance

    async def _spawn(
        self, cmd: list[str], env: dict[str, str], log_file: Path | None = None
    ) -> ProcessHandle:
        try:
            return await asyncio.to_thread(
                self._runner.spawn, cmd=cmd, env=env, cwd=BACKEND_DIR, log_file=log_file
            )
        except OSError as exc:
            logger.error("Failed to spawn simulator subprocess: %s", exc)
            raise SimulationError(
                "Failed to start the simulator: the backend could not launch the simulator process."
            ) from exc

    async def _supervise(self, instance: _Instance) -> None:
        wait_task = asyncio.ensure_future(instance.process.wait())
        grace_task = asyncio.ensure_future(asyncio.sleep(self._grace_seconds))
        done, _ = await asyncio.wait({wait_task, grace_task}, return_when=asyncio.FIRST_COMPLETED)
        grace_task.cancel()
        if wait_task in done:
            rc = await wait_task
            await self._record_exit(instance, rc)
            return
        async with self._lock:
            if instance.status == _STATE_STARTING:
                instance.status = _STATE_RUNNING
            instance.settled.set()
        rc = await wait_task
        await self._record_exit(instance, rc)

    async def _record_exit(self, instance: _Instance, rc: int) -> None:
        async with self._lock:
            if instance.status in (_STATE_STOPPING, _STATE_STOPPED):
                # A supervisor-observed exit during/after a requested stop is a
                # clean stop even if the stop handler already recorded it.
                instance.status = _STATE_STOPPED
                instance.error = None
            else:
                instance.status = _STATE_ERROR
                instance.error = _exit_reason(rc, instance.log_file)

                # Emit error event for unexpected process exit
                await publish_workflow_event(
                    workflow=WorkflowType.SIMULATION,
                    stage=WorkflowStage.SIMULATION_PROCESS_EXIT,
                    status=WorkflowStatus.ERROR,
                    message=f"Simulator process exited unexpectedly for vehicle {instance.vehicle_id} (exit code {rc})",
                    vehicle_id=str(instance.vehicle_id),
                    correlation_id=f"sim-{instance.vehicle_id}-{int(instance.started_at.timestamp())}",
                    metadata=sanitize_metadata(
                        {
                            "exit_code": rc,
                            "scenario": instance.scenario,
                            "pid": instance.process.pid if instance.process else None,
                        }
                    ),
                )
            self._finalize_locked(instance)
            instance.settled.set()

    def _finalize_locked(self, instance: _Instance) -> None:
        if self._instances.get(instance.vehicle_id) is instance:
            self._remove_pid_file(instance)
        instance.process = None

    async def _terminate(self, process: ProcessHandle) -> None:
        # POSIX terminate() = SIGTERM (graceful); Windows terminate() =
        # TerminateProcess (immediate). The timeout escalates to kill().
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=self._stop_timeout)
        except TimeoutError:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=self._stop_timeout)
            except TimeoutError:
                logger.warning("Simulator process did not exit after the stop timeout")

    async def _await_initial_state(self, instance: _Instance) -> None:
        try:
            await asyncio.wait_for(instance.settled.wait(), timeout=self._grace_seconds * 2 + 5.0)
        except TimeoutError:
            logger.warning("Simulator %s never settled after spawning", instance.vehicle_id)

    def _build_command_and_env(
        self,
        vehicle_id: UUID,
        scenario: ScenarioName,
        interval_seconds: float,
        seed: int,
    ) -> tuple[list[str], dict[str, str]]:
        settings = self._settings
        env = dict(os.environ)
        env.update(
            {
                "SIMULATOR_VEHICLE_ID": str(vehicle_id),
                "SIMULATOR_SCENARIO": scenario,
                "SIMULATOR_INTERVAL_SECONDS": repr(interval_seconds),
                "SIMULATOR_SEED": str(seed),
                "MQTT_BROKER_HOST": settings.mqtt_broker_host,
                "MQTT_BROKER_PORT": str(settings.mqtt_broker_port),
                "MQTT_TOPIC_PREFIX": settings.mqtt_topic_prefix,
                "MQTT_KEEPALIVE": str(settings.mqtt_keepalive),
                "MQTT_QOS": str(settings.mqtt_qos),
                "MQTT_RECONNECT_MAX_SECONDS": str(settings.mqtt_reconnect_max_seconds),
            }
        )
        if settings.mqtt_username is not None:
            env["MQTT_USERNAME"] = settings.mqtt_username
        if settings.mqtt_password is not None:
            env["MQTT_PASSWORD"] = settings.mqtt_password
        cmd, extra_env = python_module_command("simulator.main")
        env.update(extra_env)
        return cmd, env

    def _to_status(self, vehicle_id: UUID, instance: _Instance | None) -> SimulationStatus:
        if instance is None:
            return SimulationStatus(vehicle_id=vehicle_id, status=_STATE_STOPPED)
        return SimulationStatus(
            vehicle_id=vehicle_id,
            status=instance.status,
            scenario=instance.scenario,
            interval_seconds=instance.interval_seconds,
            seed=instance.seed,
            started_at=instance.started_at,
            error=instance.error,
        )

    @classmethod
    def _stopped_status(cls, vehicle_id: UUID) -> SimulationStatus:
        return SimulationStatus(vehicle_id=vehicle_id, status=_STATE_STOPPED)

    @staticmethod
    def _write_pid_file(path: Path, pid: int, owner_pid: int | None = None) -> None:
        try:
            # Line 1: simulator PID. Line 2: PID of the backend process that
            # spawned it (used by cleanup_stale to avoid sweeping another live
            # backend's simulators).
            if owner_pid is None:
                path.write_text(f"{pid}\n", encoding="ascii")
            else:
                path.write_text(f"{pid}\n{owner_pid}\n", encoding="ascii")
        except OSError:
            logger.warning("Cannot write simulator marker %s", path)

    @staticmethod
    def _remove_pid_file(instance: _Instance) -> None:
        try:
            instance.pid_file.unlink(missing_ok=True)
        except OSError:
            logger.debug("Cannot remove simulator marker %s", instance.pid_file)


def _venv_redirector_base(executable: str) -> str | None:
    """Return the base interpreter when ``executable`` is a Windows venv launcher.

    On Windows, CPython-created venvs ship a *launcher* ``Scripts\\python.exe``
    that spawns the base interpreter (from ``pyvenv.cfg``) as a child and waits
    for it. Plain ``sys.executable`` in such a venv therefore yields TWO
    processes per launch: the launcher we would track and terminate, and the
    worker that actually runs. Returning the base interpreter lets callers
    spawn the worker directly -- one process, clean stop/orphan semantics.
    """
    if sys.platform != "win32":
        return None
    executable_path = Path(executable)
    cfg = executable_path.parent.parent / "pyvenv.cfg"
    if not cfg.exists():
        # Some layouts keep pyvenv.cfg next to the executable itself.
        cfg = executable_path.parent / "pyvenv.cfg"
    if not cfg.exists():
        return None
    base = getattr(sys, "_base_executable", sys.executable)
    if base and Path(base) != executable_path:
        return base
    return None


def python_module_command(module: str) -> tuple[list[str], dict[str, str]]:
    """Build argv + extra env to run ``python -m <module>`` as ONE process.

    On a machine whose ``sys.executable`` is a Windows venv launcher the base
    interpreter runs directly and ``__PYVENV_LAUNCHER__`` points back at the
    venv so the child still resolves the venv's site-packages. Everywhere else
    ``sys.executable`` is used unchanged. Shared by the simulator manager and
    the subscriber supervisor so neither ever spawns a redundant launcher
    child.
    """
    extra: dict[str, str] = {}
    interpreter = _venv_redirector_base(sys.executable)
    if interpreter is None:
        return [sys.executable, "-m", module], extra
    extra["__PYVENV_LAUNCHER__"] = sys.executable
    return [interpreter, "-m", module], extra


def _read_marker_owner(path: Path) -> int | None:
    """Return the ownizing backend PID recorded in a marker file, if any.

    Markers created by older versions only wrote the simulator PID (one line);
    those read back None and are treated as eligible for orphan cleanup.
    """
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        try:
            return int(line)
        except ValueError:
            return None
    return None


def _exit_reason(rc: int, log_file: Path | None = None) -> str:
    if rc == 0:
        reason = "Simulator process exited unexpectedly"
    else:
        reason = f"Simulator process exited unexpectedly (exit code {rc})"
    if log_file is None:
        return reason
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return reason
    trimmed = lines[-_LOG_TAIL_LINES:]
    if trimmed:
        tail = "\n".join(trimmed)
        return f"{reason}\nLast simulator output:\n{tail}"
    return reason


_LOG_TAIL_LINES = 40


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _win_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _win_pid_alive(pid: int) -> bool:
    """Probe liveness without raising: OpenProcess + zero-timeout wait."""
    kernel32 = ctypes.windll.kernel32
    synchronize = 0x00100000
    query_limited = 0x1000
    handle = kernel32.OpenProcess(synchronize | query_limited, False, pid)
    if not handle:
        return kernel32.GetLastError() != _WIN_ERROR_INVALID_PARAMETER
    try:
        return kernel32.WaitForSingleObject(handle, 0) == _WIN_WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def _kill_pid(pid: int) -> None:
    # POSIX: os.kill sends the signal (SIGTERM). Windows: a positive signal
    # value maps to TerminateProcess, an immediate stop. Either way missing
    # or already-reaped processes must not raise.
    with suppress(OSError):
        os.kill(pid, signal.SIGTERM)


def get_simulation_manager() -> SimulationManager:
    """Lazily-built process-lifetime manager.

    Used by both the API dependency and the FastAPI lifespan so startup cleans
    up stale processes and shutdown terminates live ones. Injectable in tests
    through ``app.dependency_overrides``.
    """
    global _SIMULATION_MANAGER
    if _SIMULATION_MANAGER is None:
        _SIMULATION_MANAGER = SimulationManager(get_settings())
    return _SIMULATION_MANAGER


_SIMULATION_MANAGER: SimulationManager | None = None
