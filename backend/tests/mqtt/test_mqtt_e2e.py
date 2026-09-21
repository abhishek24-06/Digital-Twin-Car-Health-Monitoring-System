"""End-to-end: real MQTT broker -> real subscriber -> PostgreSQL.

Marked ``mqtt_e2e`` so the default suite excludes it; run with ``pytest -m
mqtt_e2e`` (or ``make mqtt-test``) with a broker reachable on the configured
host/port. When no broker is reachable the test skips instead of failing.

The message is produced with the ``mosquitto_pub`` CLI in a worker thread
instead of an in-process ``MQTTPublisher``: running two aiomqtt clients
(subscriber + publisher) on one SelectorEventLoop destabilizes their sockets
on Windows, and in production the simulator is a separate process anyway.
"""

import asyncio
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.telemetry import TelemetryRecord
from app.mqtt.schemas import TelemetryData, TelemetryMessage
from app.mqtt.subscriber import MQTTSubscriber

pytestmark = pytest.mark.mqtt_e2e

MOSQUITTO_PUB = Path(r"C:\Program Files\mosquitto\mosquitto_pub.exe")


def _broker_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _cli_publish(host: str, port: int, topic: str, payload: str) -> int:
    if not MOSQUITTO_PUB.exists():
        return -1
    result = subprocess.run(
        [
            str(MOSQUITTO_PUB),
            "-h",
            host,
            "-p",
            str(port),
            "-t",
            topic,
            "-m",
            payload,
            "-q",
            "1",
        ],
        capture_output=True,
        timeout=10,
    )
    return result.returncode


async def _wait_for_records(session_factory, expected: int, timeout: float = 30.0) -> bool:
    async def _count() -> int:
        async with session_factory() as session:
            total = await session.scalar(select(func.count()).select_from(TelemetryRecord))
        return int(total or 0)

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await _count() >= expected:
            return True
        await asyncio.sleep(0.2)
    return False


async def _run_case(session_factory, sample_vehicle) -> None:
    settings = Settings()
    vehicle_id = sample_vehicle["id"]
    topic = f"{settings.mqtt_topic_prefix}/{vehicle_id}/telemetry"
    message = TelemetryMessage(
        schema_version=1,
        event_id="e2e-event-1",
        vehicle_id=vehicle_id,
        timestamp=datetime.now(UTC),
        telemetry=TelemetryData(rpm=2100.0, speed=60.0, battery_voltage=13.8),
    )

    subscriber = MQTTSubscriber(settings, session_factory)
    stop_event = asyncio.Event()
    task = asyncio.create_task(subscriber.run_forever(stop_event))

    try:
        # Republish until the broker has delivered at least one record, so a
        # subscriber that is still subscribing does not lose the QoS-1 frame.
        # Each republish carries the same event_id, so idempotency must keep
        # exactly one row in the database.
        loop = asyncio.get_event_loop()
        persisted = False
        for _ in range(10):
            rc = await loop.run_in_executor(
                None,
                _cli_publish,
                settings.mqtt_broker_host,
                settings.mqtt_broker_port,
                topic,
                message.model_dump_json(),
            )
            assert rc == 0, f"mosquitto_pub failed with rc={rc}"
            if await _wait_for_records(session_factory, 1, timeout=3.0):
                persisted = True
                break
        assert persisted, "subscriber never persisted the MQTT message"

        async with session_factory() as session:
            total = await session.scalar(select(func.count()).select_from(TelemetryRecord))
            assert int(total or 0) == 1

            record = await session.scalar(select(TelemetryRecord))
            assert record.source_event_id == "e2e-event-1"
            assert str(record.vehicle_id) == vehicle_id
            assert record.rpm == 2100.0
            assert record.speed == 60.0
            assert record.raw_payload["event_id"] == "e2e-event-1"
    finally:
        stop_event.set()
        await asyncio.wait_for(task, timeout=5.0)


def test_mqtt_message_reaches_postgres(session_factory, sample_vehicle) -> None:
    settings = Settings()
    if not _broker_reachable(settings.mqtt_broker_host, settings.mqtt_broker_port):
        pytest.skip(f"no MQTT broker at {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")

    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(_run_case(session_factory, sample_vehicle))
    finally:
        loop.close()


def test_two_subscriber_processes_do_not_session_takeover() -> None:
    """Regression: two subscriber instances must not disconnect each other.

    With a fixed client id, the second process performs an MQTT session
    takeover and both processes enter an endless reconnect flap that crashes
    the Windows SelectorEventLoop with ``OSError: [WinError 10038]``. Spawn
    two real subscriber processes and assert both stay connected - no
    disconnects, reconnects or crashes.
    """
    settings = Settings()
    if not _broker_reachable(settings.mqtt_broker_host, settings.mqtt_broker_port):
        pytest.skip(f"no MQTT broker at {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")

    backend_dir = Path(__file__).resolve().parents[2]
    processes: list[subprocess.Popen] = []
    log_paths: list[Path] = []

    try:
        for _ in range(2):
            log_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".log", delete=False, dir=tempfile.gettempdir()
            )
            log_file.close()
            log_paths.append(Path(log_file.name))
            with open(log_file.name, "w", encoding="utf-8") as stream:
                processes.append(
                    subprocess.Popen(
                        [sys.executable, "-m", "app.mqtt.subscriber"],
                        cwd=backend_dir,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                    )
                )

        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            state = [content(path) for path in log_paths]
            if all("Connected to" in text for text in state):
                break
            time.sleep(0.5)

        # A session takeover disconnects the first subscriber within ~1s of the
        # second connecting. Observe both processes for a few more seconds so a
        # takeover/disconnect has time to surface in the logs before asserting.
        time.sleep(5.0)

        logs = [content(path) for path in log_paths]
        for index, text in enumerate(logs, start=1):
            assert "Connected to" in text, f"subscriber {index} never connected"
            assert "Disconnected during message iteration" not in text, (
                f"subscriber {index} lost its connection"
            )
            assert "Reconnecting to MQTT broker" not in text, (
                f"subscriber {index} entered a reconnect flap"
            )
            assert re.search(r"WinError 10038|Traceback", text) is None, (
                f"subscriber {index} crashed"
            )
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def content(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")
