"""Isolated infrastructure for the pipeline evaluation (Phase C pattern).

This module owns every side-effecting concern so the experiment drivers stay
readable and the isolation rules live in exactly one place:

* a **fail-closed** disposable-database guard (loopback only, exact test name);
* a private ``mosquitto`` broker on a free loopback port (``persistence false``);
* a real MQTT publisher and a real in-process subscriber bound to that broker;
* read helpers for telemetry and alerts.

Nothing here mocks success: when a precondition fails it raises
:class:`HarnessUnavailable` / :class:`IsolationError` and the caller reports
**NOT EXECUTED**.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models import Base
from app.models.alert import Alert
from app.models.telemetry import TelemetryRecord
from app.models.vehicle import Vehicle
from app.mqtt.client import create_mqtt_client
from app.mqtt.schemas import SCHEMA_VERSION, TelemetryData, TelemetryMessage
from app.mqtt.subscriber import MQTTSubscriber

_HOSTED_MARKERS = ("supabase", "pooler", "amazonaws", "render.com", "neon.tech")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_REQUIRED_DB_NAME = "digital_twin_eval_test"

#: Where the isolated evaluation database URL is read from, and the documented
#: loopback default used by the CLI when the variable is unset.
EVAL_DATABASE_URL_ENV = "DT_EVAL_DATABASE_URL"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_eval_test"

_MOSQUITTO_CANDIDATES = (
    Path(r"C:\Program Files\mosquitto\mosquitto.exe"),
    Path(r"C:\Program Files (x86)\mosquitto\mosquitto.exe"),
)

#: Envelope builder only passes metrics the envelope schema declares.
_TELEMETRY_FIELDS = tuple(TelemetryData.model_fields)


class IsolationError(RuntimeError):
    """The configured database is not verifiably isolated (fail closed)."""


class HarnessUnavailable(RuntimeError):
    """A required external service (broker/DB) is unavailable: NOT EXECUTED."""


# --------------------------------------------------------------------------- #
# Isolation guard
# --------------------------------------------------------------------------- #


def resolve_database_url(explicit: str | None = None) -> str:
    """Return the isolated evaluation DB URL or raise (never a hosted target)."""
    url = explicit or os.environ.get(EVAL_DATABASE_URL_ENV)
    if not url:
        raise IsolationError(
            "DT_EVAL_DATABASE_URL is not set; the pipeline evaluation needs an explicit "
            "disposable database (loopback, named digital_twin_eval_test)."
        )
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    db_name = (parsed.path or "").lstrip("/")
    if any(marker in host for marker in _HOSTED_MARKERS):
        raise IsolationError(f"refusing hosted database host {host!r}")
    if host not in _LOCAL_HOSTS:
        raise IsolationError(f"refusing non-loopback database host {host!r}")
    if db_name != _REQUIRED_DB_NAME:
        raise IsolationError(
            f"refusing database {db_name!r}; the evaluation requires the dedicated "
            f"database {_REQUIRED_DB_NAME!r}."
        )
    return url


def find_mosquitto() -> str:
    executable = shutil.which("mosquitto")
    if not executable:
        for candidate in _MOSQUITTO_CANDIDATES:
            if candidate.exists():
                executable = str(candidate)
                break
    if not executable:
        raise HarnessUnavailable("mosquitto executable not found")
    return executable


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #


def _non_rag_tables():
    return [t for t in Base.metadata.sorted_tables if not t.name.startswith("rag_")]


async def ensure_database_exists(url: str) -> None:
    """Create the disposable database if the server does not have it yet."""
    import asyncpg

    parsed = urlparse(url)
    dsn = (
        f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}/postgres"
    )
    connection = await asyncpg.connect(dsn)
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _REQUIRED_DB_NAME
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{_REQUIRED_DB_NAME}"')
    finally:
        await connection.close()


class EvaluationDatabase:
    """Owns the disposable database schema and exposes read helpers."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = create_async_engine(url)
        self.session_factory = async_sessionmaker(bind=self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        tables = _non_rag_tables()
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all, tables=tables)
            await conn.run_sync(Base.metadata.create_all, tables=tables)

    async def drop_schema(self) -> None:
        tables = _non_rag_tables()
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all, tables=tables)

    async def truncate(self) -> None:
        tables = (
            "alert_events, alerts, workflow_events, refresh_tokens, users, "
            "telemetry_records, vehicle_health_snapshots, agent_diagnoses, vehicles"
        )
        async with self.engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))

    async def create_vehicle(self, vin: str | None = None) -> UUID:
        vehicle_id = uuid4()
        async with self.session_factory() as session:
            session.add(
                Vehicle(
                    id=vehicle_id,
                    vin=vin or f"EVAL-{uuid4().hex[:12]}",
                    make="Eval",
                    model="Harness",
                    year=2026,
                )
            )
            await session.commit()
        return vehicle_id

    async def count_telemetry(self, vehicle_id: UUID, *, run_id: UUID | None = None) -> int:
        statement = (
            select(func.count())
            .select_from(TelemetryRecord)
            .where(TelemetryRecord.vehicle_id == vehicle_id)
        )
        if run_id is not None:
            statement = statement.where(TelemetryRecord.simulation_run_id == run_id)
        async with self.session_factory() as session:
            return int(await session.scalar(statement) or 0)

    async def telemetry_created_at(self, vehicle_id: UUID, event_id: str) -> datetime | None:
        async with self.session_factory() as session:
            return await session.scalar(
                select(TelemetryRecord.created_at).where(
                    TelemetryRecord.vehicle_id == vehicle_id,
                    TelemetryRecord.source_event_id == event_id,
                )
            )

    async def telemetry_timestamps(self, vehicle_id: UUID) -> list[datetime]:
        """All persisted source timestamps for a vehicle, oldest-first."""
        async with self.session_factory() as session:
            result = await session.scalars(
                select(TelemetryRecord.timestamp)
                .where(TelemetryRecord.vehicle_id == vehicle_id)
                .order_by(TelemetryRecord.timestamp.asc())
            )
            return list(result.all())

    async def alert_rows(self, vehicle_id: UUID) -> list[dict[str, object]]:
        """Every persisted alert row (including resolved), oldest first."""
        async with self.session_factory() as session:
            result = await session.scalars(
                select(Alert)
                .where(Alert.vehicle_id == vehicle_id)
                .order_by(Alert.first_seen_at.asc(), Alert.id.asc())
            )
            alerts = list(result.all())
        return [
            {
                "alert_id": str(a.id),
                "rule_id": a.rule_id,
                "severity": a.severity,
                "status": a.status,
                "provisional": bool(a.provisional),
                "occurrence_count": int(a.occurrence_count),
                "first_seen_at": a.first_seen_at,
                "last_seen_at": a.last_seen_at,
                "resolved_at": a.resolved_at,
                "simulation_run_id": (str(a.simulation_run_id) if a.simulation_run_id else None),
            }
            for a in alerts
        ]

    async def dispose(self) -> None:
        await self.engine.dispose()


# --------------------------------------------------------------------------- #
# Broker + settings + publisher + subscriber
# --------------------------------------------------------------------------- #


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass
class IsolatedBroker:
    host: str
    port: int
    executable: str
    conf_dir: Path
    log_path: Path
    process: subprocess.Popen | None = None

    def _write_conf(self) -> Path:
        conf = self.conf_dir / "mosquitto.conf"
        conf.write_text(
            "# Generated by the pipeline-evaluation harness: disposable, loopback only.\n"
            f"listener {self.port} 127.0.0.1\n"
            "allow_anonymous true\n"
            "persistence false\n"
            "log_dest stdout\n",
            encoding="utf-8",
        )
        return conf

    @property
    def log_tail(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            return "<no broker log>"

    def start(self) -> None:
        conf = self._write_conf()
        with open(self.log_path, "a", encoding="utf-8") as log_handle:
            self.process = subprocess.Popen(
                [self.executable, "-c", str(conf)],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                cwd=str(self.conf_dir),
            )
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if _is_reachable(self.host, self.port):
                return
            if self.process.poll() is not None:
                raise HarnessUnavailable(
                    f"mosquitto exited immediately (rc={self.process.returncode}); "
                    f"log: {self.log_path}"
                )
            time.sleep(0.1)
        raise HarnessUnavailable(f"mosquitto never accepted connections on {self.host}:{self.port}")

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def restart(self) -> None:
        self.stop()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and _is_reachable(self.host, self.port):
            time.sleep(0.05)
        self.start()


@contextlib.contextmanager
def running_broker(executable: str) -> Iterator[IsolatedBroker]:
    tmp = Path(os.environ.get("TEMP") or ".")
    conf_dir = tmp / f"dtwin-eval-broker-{uuid4().hex[:8]}"
    conf_dir.mkdir(parents=True, exist_ok=True)
    broker = IsolatedBroker(
        host="127.0.0.1",
        port=_free_port(),
        executable=executable,
        conf_dir=conf_dir,
        log_path=conf_dir / "mosquitto.log",
    )
    broker.start()
    try:
        yield broker
    finally:
        broker.stop()
        shutil.rmtree(conf_dir, ignore_errors=True)


def broker_settings(
    broker: IsolatedBroker,
    *,
    retry_attempts: int = 3,
    batch_max_messages: int = 1,
    batch_flush_seconds: float = 5.0,
) -> Settings:
    """Settings bound to the private broker, tuned for a deterministic harness.

    ``batch_max_messages=1`` makes the subscriber persist each sample as its own
    batch, so the flush timer only fires while the feed is idle. The flush timeout
    is deliberately generous: the subscriber's idle wait is a cancellable
    ``anext`` on the message iterator, and a cancellation racing an inbound
    message can drop an already-acknowledged sample. A long timeout removes that
    race for the paced (≈1 Hz) streaming experiment without changing batching.
    """
    base = Settings()
    return base.model_copy(
        update={
            "mqtt_broker_host": broker.host,
            "mqtt_broker_port": broker.port,
            "mqtt_client_id": f"dtwin-eval-{uuid4().hex[:10]}",
            "mqtt_batch_max_messages": batch_max_messages,
            "mqtt_batch_flush_seconds": batch_flush_seconds,
            "mqtt_message_retry_attempts": retry_attempts,
            "mqtt_reconnect_max_seconds": 3.0,
        }
    )


def build_envelope(
    vehicle_id: UUID,
    event_id: str,
    run_id: UUID | None,
    timestamp: datetime,
    values: dict[str, float | None],
) -> bytes:
    telemetry = TelemetryData(**{name: values.get(name) for name in _TELEMETRY_FIELDS})
    envelope = TelemetryMessage(
        schema_version=SCHEMA_VERSION,
        event_id=event_id,
        vehicle_id=vehicle_id,
        simulation_run_id=run_id,
        timestamp=timestamp,
        telemetry=telemetry,
    )
    return envelope.model_dump_json().encode("utf-8")


class Publisher:
    """A single long-lived MQTT connection used to publish telemetry."""

    def __init__(self, settings) -> None:
        # A unique client id per connection: the broker evicts a duplicate id, so
        # re-opening a publisher (e.g. after a broker restart) must not reuse the
        # subscriber's id.
        self._settings = settings.model_copy(
            update={"mqtt_client_id": f"{settings.mqtt_client_id}-pub-{uuid4().hex[:8]}"}
        )
        self._client = create_mqtt_client(self._settings)
        self._connected = None

    async def __aenter__(self) -> Publisher:
        self._connected = await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.__aexit__(*exc)

    async def publish(self, topic: str, payload: bytes) -> None:
        await self._connected.publish(topic, payload, qos=self._settings.mqtt_qos)


@contextlib.asynccontextmanager
async def running_subscriber(settings, session_factory) -> AsyncIterator[None]:
    subscriber = MQTTSubscriber(settings, session_factory)
    stop = asyncio.Event()
    task = asyncio.create_task(subscriber.run_forever(stop))
    try:
        await asyncio.sleep(0.6)  # allow connect + subscribe
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=10.0)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def wait_for_telemetry(
    database: EvaluationDatabase,
    vehicle_id: UUID,
    expected: int,
    *,
    run_id: UUID | None = None,
    timeout: float = 30.0,
) -> int:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    observed = 0
    while loop.time() < deadline:
        observed = await database.count_telemetry(vehicle_id, run_id=run_id)
        if observed >= expected:
            return observed
        await asyncio.sleep(0.1)
    return observed


# --------------------------------------------------------------------------- #
# Environment provenance
# --------------------------------------------------------------------------- #


def environment_info(database_url: str, broker: IsolatedBroker, settings) -> dict[str, object]:
    parsed = urlparse(database_url)
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "database_host": parsed.hostname,
        "database_name": (parsed.path or "").lstrip("/"),
        "broker_host": broker.host,
        "broker_port": broker.port,
        "broker_persistence": False,
        "mqtt_qos": settings.mqtt_qos,
        "mqtt_batch_max_messages": settings.mqtt_batch_max_messages,
        "mqtt_batch_flush_seconds": settings.mqtt_batch_flush_seconds,
        "analysis_window_minutes": settings.health_analysis_window_minutes,
        "expected_interval_seconds": settings.health_expected_interval_seconds,
        "analysis_config_source": "app.core.config.get_settings() (services) + broker-bound copy (MQTT)",
        "clock_semantics": {
            "rq3_alerts": (
                "replayed on the episode's synthetic clock: each persisted snapshot is "
                "re-analysed with generated_at=point.timestamp and fed to "
                "AlertService.sync_from_snapshot in timestamp order"
            ),
            "rq3_recovery": (
                "two sessions on one vehicle: fault session (synthetic clock T) then a "
                "condition-free normal session (clock T + 1 day) so the two never overlap"
            ),
            "rq4_latency": (
                "separate wall-clock streaming run (generated_at=None); ingest latency is "
                "publish_ts -> persisted created_at using a monotonic clock, so it is "
                "host-local and excludes any external network hop"
            ),
            "rq6_robustness": (
                "wall-clock injection against the live subscriber; injected faults and the "
                "resulting persisted row counts are measured, not simulated"
            ),
        },
    }


__all__ = [
    "DEFAULT_DATABASE_URL",
    "EVAL_DATABASE_URL_ENV",
    "EvaluationDatabase",
    "HarnessUnavailable",
    "IsolatedBroker",
    "IsolationError",
    "Publisher",
    "build_envelope",
    "broker_settings",
    "ensure_database_exists",
    "environment_info",
    "find_mosquitto",
    "resolve_database_url",
    "running_broker",
    "running_subscriber",
    "wait_for_telemetry",
]
