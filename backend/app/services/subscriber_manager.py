"""Backend-owned MQTT subscriber supervision.

Simulation Control can only report an honest "running" when telemetry is
*actually* landing in the database. Historically the subscriber was a separate
process launched by ``scripts/dt-start.ps1``; a manually started API (e.g.
``uvicorn --reload``) therefore ran simulators whose published messages went
nowhere. This module gives the backend a supervised subscriber:

* on the way up the supervisor ensures ``python -m app.mqtt.subscriber`` runs
  under the backend's own process tree;
* an unexpected exit is recorded and the process is restarted with backoff;
* ``health()`` feeds the simulation status routes, which downgrade a vehicle
  to ``degraded`` while ingestion is offline instead of showing a hollow
  "running";
* PID markers are owner-tagged exactly like simulator markers, so a restarted
  backend can reclaim a subscriber orphaned by the previous run before it
  spawns a duplicate.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.simulation_manager import (
    BACKEND_DIR,
    ProcessHandle,
    RealProcessRunner,
    _exit_reason,
    _kill_pid,
    _pid_alive,
    _read_marker_owner,
    python_module_command,
)

logger = logging.getLogger(__name__)

_MARKER_NAME = "subscriber.pid"
_BACKOFF_BASE_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 16.0


@dataclass
class SubscriberHealth:
    """Snapshot of the subscriber's process health exposed to the API layer."""

    running: bool
    started_at: datetime | None = None
    last_error: str | None = None
    restarts: int = 0


class SubscriberSupervisor:
    """Supervises one subscriber subprocess for the whole backend."""

    def __init__(
        self,
        settings: Settings,
        runner=None,  # ProcessRunner for tests
        *,
        runtime_dir: Path | None = None,
        stop_timeout_seconds: float | None = None,
        auto_restart: bool = True,
    ) -> None:
        self._settings = settings
        self._runner = runner if runner is not None else RealProcessRunner()
        self._runtime_dir = (
            runtime_dir if runtime_dir is not None else Path(settings.simulation_runtime_dir)
        )
        self._stop_timeout = (
            stop_timeout_seconds
            if stop_timeout_seconds is not None
            else settings.simulation_stop_timeout_seconds
        )
        self._auto_restart = auto_restart
        try:
            self._runtime_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Cannot create subscriber marker dir %s", self._runtime_dir)
        self._process: ProcessHandle | None = None
        self._started_at: datetime | None = None
        self._last_error: str | None = None
        self._restarts = 0
        self._closed = False
        self._monitor_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def _pid_file(self) -> Path:
        return self._runtime_dir / _MARKER_NAME

    @property
    def _log_file(self) -> Path:
        return self._runtime_dir / "subscriber.log"

    async def ensure_running(self) -> SubscriberHealth:
        """Start the subscriber if it is not already running (idempotent)."""
        async with self._lock:
            if self._closed:
                return self._health()
            if self._alive():
                return self._health()
            self._reclaim_orphan_locked()
            await self._spawn_locked()
        return self._health()

    async def restart(self) -> SubscriberHealth:
        """Stop any subscriber and start a fresh one."""
        async with self._lock:
            if self._process is not None and self._process.poll() is None:
                await self._terminate(self._process)
                self._forget_locked()
            self._reclaim_orphan_locked()
            await self._spawn_locked()
        return self._health()

    async def health(self) -> SubscriberHealth:
        async with self._lock:
            return self._health()

    async def shutdown(self) -> None:
        """Terminate the subscriber and stop its monitor. Idempotent."""
        async with self._lock:
            process = self._process
            self._process = None
            self._closed = True
        if process is not None:
            await self._terminate(process)
            async with self._lock:
                self._forget_locked()
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    async def _spawn_locked(self) -> None:
        cmd, extra_env = python_module_command("app.mqtt.subscriber")
        env = _subscriber_env(self._settings, extra_env)
        process = await asyncio.to_thread(
            self._runner.spawn,
            cmd=cmd,
            env=env,
            cwd=BACKEND_DIR,
            log_file=self._log_file,
        )
        self._process = process
        self._started_at = datetime.now(UTC)
        self._last_error = None
        self._write_pid_file(process.pid)
        self._monitor_task = asyncio.create_task(self._supervise(), name="subscriber-supervisor")

    async def _supervise(self) -> None:
        process = self._process
        if process is None:
            return
        rc = await process.wait()
        async with self._lock:
            will_restart = self._auto_restart and not self._closed
            self._last_error = _exit_reason(rc, self._log_file)
            self._process = None
            self._remove_pid_file()
            if will_restart:
                self._restarts += 1
        if not will_restart:
            logger.warning("MQTT subscriber exited (rc=%s)", rc)
            return
        backoff = min(
            _BACKOFF_BASE_SECONDS * (2 ** min(max(self._restarts - 1, 0), 4)),
            _MAX_BACKOFF_SECONDS,
        )
        logger.warning(
            "MQTT subscriber exited (rc=%s); restarting in %.0fs",
            rc,
            backoff,
        )
        await asyncio.sleep(backoff)
        await self.ensure_running()

    def _alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _health(self) -> SubscriberHealth:
        return SubscriberHealth(
            running=self._alive(),
            started_at=self._started_at,
            last_error=self._last_error,
            restarts=self._restarts,
        )

    def _forget_locked(self) -> None:
        self._remove_pid_file()
        self._process = None
        self._started_at = None

    def _reclaim_orphan_locked(self) -> None:
        """Terminate a subscriber pid from a previous backend run, if any.

        Owner-tagged markers are skipped when the recorded owner is still a
        live process -- that backend instance owns its subscriber and must not
        be torn down as if it were an orphan.
        """
        marker = self._pid_file
        if not marker.exists():
            return
        pid = _read_marker_pid(marker)
        owner_pid = _read_marker_owner(marker)
        if pid is None:
            return
        if (
            self._process is not None
            and self._process.poll() is None
            and (self._process.pid == pid or not _pid_alive(pid))
        ):
            return
        if owner_pid is not None and owner_pid != os.getpid() and _pid_alive(owner_pid):
            return
        if _pid_alive(pid):
            logger.warning(
                "Terminating orphaned MQTT subscriber pid=%s from a previous backend run",
                pid,
            )
            _kill_pid(pid)
        marker.unlink(missing_ok=True)

    def _write_pid_file(self, pid: int) -> None:
        try:
            self._pid_file.write_text(f"{pid}\n{os.getpid()}\n", encoding="ascii")
        except OSError:
            logger.warning("Cannot write subscriber marker %s", self._pid_file)

    def _remove_pid_file(self) -> None:
        try:
            self._pid_file.unlink(missing_ok=True)
        except OSError:
            logger.debug("Cannot remove subscriber marker %s", self._pid_file)

    async def _terminate(self, process: ProcessHandle) -> None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=self._stop_timeout)
        except TimeoutError:
            process.kill()
            with suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=self._stop_timeout)


def _read_marker_pid(path: Path) -> int | None:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            return int(line)
        except ValueError:
            return None
    return None


def _subscriber_env(settings: Settings, extra: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "MQTT_BROKER_HOST": settings.mqtt_broker_host,
            "MQTT_BROKER_PORT": str(settings.mqtt_broker_port),
            "MQTT_TOPIC_PREFIX": settings.mqtt_topic_prefix,
            "MQTT_KEEPALIVE": str(settings.mqtt_keepalive),
            "MQTT_QOS": str(settings.mqtt_qos),
            "MQTT_RECONNECT_MAX_SECONDS": str(settings.mqtt_reconnect_max_seconds),
            "MQTT_MESSAGE_RETRY_ATTEMPTS": str(settings.mqtt_message_retry_attempts),
            **extra,
        }
    )
    if settings.mqtt_username is not None:
        env["MQTT_USERNAME"] = settings.mqtt_username
    if settings.mqtt_password is not None:
        env["MQTT_PASSWORD"] = settings.mqtt_password
    return env


def get_subscriber_supervisor() -> SubscriberSupervisor:
    """Lazily-built process-lifetime supervisor.

    Used by both the API routes (health checks) and the FastAPI lifespan
    (startup ensure / shutdown terminate). Injectable in tests through
    ``app.dependency_overrides``.
    """
    global _SUBSCRIBER_SUPERVISOR
    if _SUBSCRIBER_SUPERVISOR is None:
        _SUBSCRIBER_SUPERVISOR = SubscriberSupervisor(get_settings())
    return _SUBSCRIBER_SUPERVISOR


_SUBSCRIBER_SUPERVISOR: SubscriberSupervisor | None = None
