"""Fixtures for the Phase C MQTT integration suite.

This suite runs against a **real isolated Mosquitto broker** and a **dedicated
disposable PostgreSQL database** (see `SYSTEM_DOCUMENTATION.md` §14).

Safety contract
---------------
* ``DT_MQTT_TEST_DATABASE_URL`` must be set explicitly; when absent the suite
  **skips** so the ordinary (hermetic) test run never needs a broker.
* When set, it is **fail-closed**: the target must be loopback and the database
  must be named ``digital_twin_mqtt_test``. Anything else raises.
* The broker is a private ``mosquitto`` process on a free loopback port with
  ``persistence false`` -- it never shares state with a developer's broker.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.models import Base
from app.models.telemetry import TelemetryRecord
from app.models.vehicle import Vehicle

MQTT_TEST_DATABASE_URL_ENV = "DT_MQTT_TEST_DATABASE_URL"
REQUIRED_DB_NAME = "digital_twin_mqtt_test"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
HOSTED_MARKERS = ("supabase", "pooler", "amazonaws", "render.com", "neon.tech")

_MOSQUITTO_CANDIDATES = (
    Path(r"C:\Program Files\mosquitto\mosquitto.exe"),
    Path(r"C:\Program Files (x86)\mosquitto\mosquitto.exe"),
)
_MOSQUITTO_PUB_CANDIDATES = (
    Path(r"C:\Program Files\mosquitto\mosquitto_pub.exe"),
    Path(r"C:\Program Files (x86)\mosquitto\mosquitto_pub.exe"),
)


# --------------------------------------------------------------------------- #
# Disposable database
# --------------------------------------------------------------------------- #


def _require_isolated_database_url() -> str:
    url = os.environ.get(MQTT_TEST_DATABASE_URL_ENV)
    if not url:
        pytest.skip(
            f"{MQTT_TEST_DATABASE_URL_ENV} is not set; the MQTT integration suite needs an "
            "explicit disposable database (see SYSTEM_DOCUMENTATION.md §14)."
        )

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    db_name = (parsed.path or "").lstrip("/")

    if any(marker in host for marker in HOSTED_MARKERS):
        raise RuntimeError(
            f"Refusing to run MQTT integration tests against a hosted database host {host!r}."
        )
    if host not in LOCAL_HOSTS:
        raise RuntimeError(
            f"Refusing to run MQTT integration tests against non-loopback host {host!r}."
        )
    if db_name != REQUIRED_DB_NAME:
        raise RuntimeError(
            f"Refusing database {db_name!r}: the MQTT integration suite demands a dedicated "
            f"database named {REQUIRED_DB_NAME!r}."
        )
    return url


async def _ensure_database_exists(url: str) -> None:
    parsed = urlparse(url)
    conn = await asyncpg.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", REQUIRED_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{REQUIRED_DB_NAME}"')
    finally:
        await conn.close()


def _non_rag_tables() -> list:
    return [t for t in Base.metadata.sorted_tables if not t.name.startswith("rag_")]


class MqttDatabase:
    """Async helpers over the disposable database.

    Uses ``NullPool`` so every operation opens and closes its own connection in
    whatever event loop is currently running; no connection outlives a loop.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @property
    def session_factory(self) -> async_sessionmaker:
        return async_sessionmaker(bind=self._engine, expire_on_commit=False)

    async def create_vehicle(self) -> UUID:
        factory = self.session_factory
        async with factory() as session:
            vehicle = Vehicle(
                id=uuid4(),
                vin=f"MQTT-{uuid4().hex[:12]}",
                make="Test",
                model="Camper",
                year=2024,
            )
            session.add(vehicle)
            await session.commit()
            return vehicle.id

    async def truncate(self) -> None:
        tables = (
            "alert_events, alerts, workflow_events, refresh_tokens, users, "
            "telemetry_records, vehicle_health_snapshots, agent_diagnoses, vehicles"
        )
        async with self._engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))

    async def count_telemetry(self, vehicle_id: UUID) -> int:
        factory = self.session_factory
        async with factory() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(TelemetryRecord)
                .where(TelemetryRecord.vehicle_id == vehicle_id)
            )
        return int(total or 0)

    async def telemetry_rows(self, vehicle_id: UUID) -> list[TelemetryRecord]:
        factory = self.session_factory
        async with factory() as session:
            result = await session.scalars(
                select(TelemetryRecord)
                .where(TelemetryRecord.vehicle_id == vehicle_id)
                .order_by(TelemetryRecord.timestamp)
            )
            return list(result)


@pytest.fixture(scope="session")
def mqtt_database_url() -> str:
    return _require_isolated_database_url()


@pytest.fixture(scope="session")
def mqtt_database(mqtt_database_url: str) -> Iterator[MqttDatabase]:
    loop = asyncio.SelectorEventLoop()
    engine = create_async_engine(mqtt_database_url, poolclass=NullPool)
    tables = _non_rag_tables()

    async def _create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all, tables=tables)
            await conn.run_sync(Base.metadata.create_all, tables=tables)

    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all, tables=tables)
        await engine.dispose()

    loop.run_until_complete(_ensure_database_exists(mqtt_database_url))
    loop.run_until_complete(_create())
    try:
        yield MqttDatabase(engine)
    finally:
        # Cleanup must survive a failing test: drop tables and dispose the pool.
        loop.run_until_complete(_drop())
        loop.close()


# --------------------------------------------------------------------------- #
# Isolated broker
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
            "# Generated by the MQTT integration harness: disposable, loopback only.\n"
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
                raise RuntimeError(
                    f"mosquitto exited immediately (rc={self.process.returncode}); "
                    f"log: {self.log_path}"
                )
            time.sleep(0.1)
        raise RuntimeError(f"mosquitto never accepted connections on {self.host}:{self.port}")

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


@pytest.fixture(scope="session")
def mosquitto_executable() -> str:
    executable = shutil.which("mosquitto")
    if not executable:
        for candidate in _MOSQUITTO_CANDIDATES:
            if candidate.exists():
                executable = str(candidate)
                break
    if not executable:
        pytest.skip("mosquitto executable not found; skipping MQTT integration tests.")
    return executable


@pytest.fixture(scope="session")
def mosquitto_pub_executable() -> str:
    executable = shutil.which("mosquitto_pub")
    if not executable:
        for candidate in _MOSQUITTO_PUB_CANDIDATES:
            if candidate.exists():
                executable = str(candidate)
                break
    if not executable:
        pytest.skip("mosquitto_pub executable not found; skipping MQTT integration tests.")
    return executable


@pytest.fixture
def broker(mosquitto_executable: str) -> Iterator[IsolatedBroker]:
    tmp = Path(os.environ.get("TEMP") or ".")
    conf_dir = tmp / f"dtwin-mqtt-broker-{uuid4().hex[:8]}"
    conf_dir.mkdir(parents=True, exist_ok=True)
    handle = IsolatedBroker(
        host="127.0.0.1",
        port=_free_port(),
        executable=mosquitto_executable,
        conf_dir=conf_dir,
        log_path=conf_dir / "mosquitto.log",
    )
    handle.start()
    try:
        yield handle
    finally:
        handle.stop()
        shutil.rmtree(conf_dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Settings + publish callable
# --------------------------------------------------------------------------- #


def make_settings(broker: IsolatedBroker, *, retry_attempts: int = 3) -> Settings:
    """A Settings copy bound to the isolated broker and a unique client id."""
    settings = Settings()
    return settings.model_copy(
        update={
            "mqtt_broker_host": broker.host,
            "mqtt_broker_port": broker.port,
            "mqtt_client_id": f"dtwin-it-{uuid4().hex[:10]}",
            "mqtt_batch_max_messages": 1,
            "mqtt_batch_flush_seconds": 0.2,
            "mqtt_message_retry_attempts": retry_attempts,
            "mqtt_reconnect_max_seconds": 3.0,
        }
    )


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    """Expose :func:`make_settings` so tests can build broker-bound settings."""
    return make_settings


@pytest.fixture
def publish_fn(
    broker: IsolatedBroker, mosquitto_pub_executable: str
) -> Callable[[str, str], int]:
    def _publish(topic: str, payload: str) -> int:
        result = subprocess.run(
            [
                mosquitto_pub_executable,
                "-h",
                broker.host,
                "-p",
                str(broker.port),
                "-t",
                topic,
                "-m",
                payload,
                "-q",
                "1",
            ],
            capture_output=True,
            timeout=15,
        )
        return result.returncode

    return _publish


def unique_event_id(prefix: str = "evt") -> str:
    return f"{prefix}-{uuid4().hex[:12]}"
