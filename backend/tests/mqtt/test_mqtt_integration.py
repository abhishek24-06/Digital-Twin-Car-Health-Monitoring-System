"""Phase C: real MQTT -> subscriber -> PostgreSQL integration acceptance.

These tests exercise the production telemetry path end-to-end against a real
**isolated Mosquitto broker** and a dedicated **disposable database**. They are
excluded from the hermetic suite and run via ``make mqtt-integration``.

Scenarios covered:
* publish -> validate -> persist
* duplicate delivery is idempotent (``(vehicle_id, source_event_id)``)
* malformed / unrelated / unknown-vehicle messages are ignored without killing
  the stream
* delayed and out-of-order messages are stored with their own timestamps
* broker disconnect/restart: the subscriber reconnects and resumes
* transient database failure is retried
* retry exhaustion is logged and never crashes the subscriber
* simulator restart produces fresh, isolated run ids
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.telemetry import TelemetryRecord
from app.mqtt.schemas import TelemetryData, TelemetryMessage
from app.mqtt.subscriber import MQTTSubscriber
from app.services.simulation_manager import SimulationManager

pytestmark = pytest.mark.mqtt_integration


def run_selector(coro) -> object:
    """Run a coroutine on a SelectorEventLoop (aiomqtt needs ``add_reader``)."""
    loop = asyncio.SelectorEventLoop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def envelope(
    vehicle_id: UUID,
    event_id: str,
    *,
    rpm: float | None = None,
    speed: float | None = None,
    run_id: UUID | None = None,
    timestamp: datetime | None = None,
) -> str:
    return TelemetryMessage(
        schema_version=2,
        event_id=event_id,
        vehicle_id=vehicle_id,
        simulation_run_id=run_id,
        timestamp=timestamp or datetime.now(UTC),
        telemetry=TelemetryData(rpm=rpm, speed=speed),
    ).model_dump_json()


@asynccontextmanager
async def running_subscriber(settings: Settings, session_factory) -> AsyncIterator[MQTTSubscriber]:
    subscriber = MQTTSubscriber(settings, session_factory)
    stop = asyncio.Event()
    task = asyncio.create_task(subscriber.run_forever(stop))
    try:
        await asyncio.sleep(0.5)  # allow connect + subscribe
        yield subscriber
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=10.0)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def publish_until(
    publish: Callable[[str, str], int],
    db,
    vehicle_id: UUID,
    topic: str,
    payloads: list[str],
    expected: int,
    *,
    timeout: float = 25.0,
) -> None:
    """Republish until exactly ``expected`` rows land (event-id dedup keeps it exact)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for payload in payloads:
            await loop.run_in_executor(None, publish, topic, payload)
        await asyncio.sleep(0.4)
        if await db.count_telemetry(vehicle_id) >= expected:
            return
    raise AssertionError(
        f"expected {expected} telemetry rows for {vehicle_id}; "
        f"got {await db.count_telemetry(vehicle_id)}"
    )


async def _publish(publish_fn: Callable[[str, str], int], topic: str, payload: str) -> None:
    await asyncio.get_running_loop().run_in_executor(None, publish_fn, topic, payload)


# --------------------------------------------------------------------------- #


def test_publish_persists_and_dedupes_duplicate_delivery(
    broker, mqtt_database, publish_fn, settings_factory
) -> None:
    settings = settings_factory(broker)

    async def case() -> None:
        await mqtt_database.truncate()
        vehicle_id = await mqtt_database.create_vehicle()
        topic = f"{settings.mqtt_topic_prefix}/{vehicle_id}/telemetry"
        first = envelope(vehicle_id, "evt-1", rpm=1500.0, speed=40.0)
        duplicate = envelope(vehicle_id, "evt-1", rpm=1500.0, speed=40.0)
        second = envelope(vehicle_id, "evt-2", rpm=2000.0, speed=55.0)

        async with running_subscriber(settings, mqtt_database.session_factory):
            await publish_until(
                publish_fn, mqtt_database, vehicle_id, topic, [first, duplicate, second], 2
            )

        rows = await mqtt_database.telemetry_rows(vehicle_id)
        assert len(rows) == 2
        assert {row.source_event_id for row in rows} == {"evt-1", "evt-2"}
        by_event = {row.source_event_id: row for row in rows}
        assert by_event["evt-1"].rpm == 1500.0
        assert by_event["evt-2"].speed == 55.0

    run_selector(case())


def test_malformed_and_unknown_messages_do_not_break_the_stream(
    broker, mqtt_database, publish_fn, settings_factory
) -> None:
    settings = settings_factory(broker)

    async def case() -> None:
        await mqtt_database.truncate()
        vehicle_id = await mqtt_database.create_vehicle()
        unknown_vehicle = uuid4()
        topic = f"{settings.mqtt_topic_prefix}/{vehicle_id}/telemetry"
        unknown_topic = f"{settings.mqtt_topic_prefix}/{unknown_vehicle}/telemetry"
        good = envelope(vehicle_id, "evt-good", rpm=1750.0, speed=60.0)

        malformed = [
            "this is not json",
            json.dumps({"schema_version": 2}),
            json.dumps(
                {"schema_version": 2, "event_id": "x", "vehicle_id": str(uuid4())}
            ),
        ]

        async with running_subscriber(settings, mqtt_database.session_factory):
            # Interleave malformed / unrelated / unknown frames with the good one.
            await publish_until(
                publish_fn, mqtt_database, vehicle_id, topic, [*malformed, good], 1
            )
            for _ in range(2):
                await _publish(publish_fn, unknown_topic, envelope(unknown_vehicle, "evt-unknown"))
                await _publish(publish_fn, "unrelated/topic", "{}")
                await asyncio.sleep(0.3)

        assert await mqtt_database.count_telemetry(vehicle_id) == 1
        assert await mqtt_database.count_telemetry(unknown_vehicle) == 0

    run_selector(case())


def test_out_of_order_and_delayed_messages_keep_their_timestamps(
    broker, mqtt_database, publish_fn, settings_factory
) -> None:
    settings = settings_factory(broker)

    async def case() -> None:
        await mqtt_database.truncate()
        vehicle_id = await mqtt_database.create_vehicle()
        topic = f"{settings.mqtt_topic_prefix}/{vehicle_id}/telemetry"
        now = datetime.now(UTC)
        later = envelope(vehicle_id, "evt-later", rpm=2000.0, timestamp=now)
        delayed = envelope(
            vehicle_id, "evt-earlier", rpm=1000.0, timestamp=now - timedelta(minutes=5)
        )

        async with running_subscriber(settings, mqtt_database.session_factory):
            # The later sample is delivered first: ordering must not be
            # "corrected" and neither timestamp may be overwritten.
            await publish_until(publish_fn, mqtt_database, vehicle_id, topic, [later, delayed], 2)

        rows = await mqtt_database.telemetry_rows(vehicle_id)
        assert len(rows) == 2
        assert rows[0].source_event_id == "evt-earlier"
        assert rows[1].source_event_id == "evt-later"
        assert (rows[1].timestamp - rows[0].timestamp) >= timedelta(minutes=4)

    run_selector(case())


def test_broker_restart_reconnects_and_resumes(
    broker, mqtt_database, publish_fn, settings_factory
) -> None:
    settings = settings_factory(broker)

    async def case() -> None:
        await mqtt_database.truncate()
        vehicle_id = await mqtt_database.create_vehicle()
        topic = f"{settings.mqtt_topic_prefix}/{vehicle_id}/telemetry"

        async with running_subscriber(settings, mqtt_database.session_factory):
            await publish_until(
                publish_fn,
                mqtt_database,
                vehicle_id,
                topic,
                [envelope(vehicle_id, "evt-before", rpm=1200.0)],
                1,
            )

            # Hard-stop the broker: the subscriber's connection drops and it must
            # retry with backoff, then resume once the broker returns.
            broker.restart()
            await asyncio.sleep(3.0)

            await publish_until(
                publish_fn,
                mqtt_database,
                vehicle_id,
                topic,
                [envelope(vehicle_id, "evt-after", rpm=2600.0)],
                2,
                timeout=35.0,
            )

        rows = await mqtt_database.telemetry_rows(vehicle_id)
        assert {row.source_event_id for row in rows} == {"evt-before", "evt-after"}

    run_selector(case())


class FlakySessionFactory:
    """Session factory that raises a fixed number of times before succeeding."""

    def __init__(self, real, fail_times: int) -> None:
        self._real = real
        self._remaining = fail_times
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise OSError("simulated transient database outage")
        return self._real()


def test_transient_database_failure_is_retried(
    broker, mqtt_database, publish_fn, settings_factory
) -> None:
    settings = settings_factory(broker, retry_attempts=4)

    async def case() -> None:
        await mqtt_database.truncate()
        vehicle_id = await mqtt_database.create_vehicle()
        topic = f"{settings.mqtt_topic_prefix}/{vehicle_id}/telemetry"
        flaky = FlakySessionFactory(mqtt_database.session_factory, fail_times=2)

        async with running_subscriber(settings, flaky):
            await publish_until(
                publish_fn,
                mqtt_database,
                vehicle_id,
                topic,
                [envelope(vehicle_id, "evt-retry", rpm=1400.0)],
                1,
                timeout=30.0,
            )

        assert flaky.calls >= 3
        assert await mqtt_database.count_telemetry(vehicle_id) == 1

    run_selector(case())


def test_retry_exhaustion_does_not_crash_subscriber(
    broker, mqtt_database, publish_fn, settings_factory
) -> None:
    settings = settings_factory(broker, retry_attempts=2)

    async def case() -> None:
        await mqtt_database.truncate()
        vehicle_id = await mqtt_database.create_vehicle()
        topic = f"{settings.mqtt_topic_prefix}/{vehicle_id}/telemetry"
        always_fail = FlakySessionFactory(mqtt_database.session_factory, fail_times=10_000)

        subscriber = MQTTSubscriber(settings, always_fail)
        stop = asyncio.Event()
        task = asyncio.create_task(subscriber.run_forever(stop))
        try:
            await asyncio.sleep(0.5)
            await _publish(publish_fn, topic, envelope(vehicle_id, "evt-doomed", rpm=1000.0))
            # Two attempts with a 1s backoff, then the batch is abandoned.
            await asyncio.sleep(4.0)
            assert not task.done(), "subscriber crashed on retry exhaustion"
            assert await mqtt_database.count_telemetry(vehicle_id) == 0
        finally:
            stop.set()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=10.0)

    run_selector(case())


async def _wait_for_run(db, vehicle_id: UUID, run_id: UUID, timeout: float = 30.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        factory = db.session_factory
        async with factory() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(TelemetryRecord)
                .where(
                    TelemetryRecord.vehicle_id == vehicle_id,
                    TelemetryRecord.simulation_run_id == run_id,
                )
            )
        if int(total or 0) >= 1:
            return
        await asyncio.sleep(0.5)
    raise AssertionError(f"no telemetry recorded for run {run_id}")


def test_simulator_restart_isolates_run_ids(
    broker, mqtt_database, settings_factory, tmp_path: Path
) -> None:
    """A real simulator subprocess publishes through the broker; a restart mints
    a fresh run id and both runs stay distinguishable in the database."""
    settings = settings_factory(broker)

    async def case() -> None:
        await mqtt_database.truncate()
        vehicle_id = await mqtt_database.create_vehicle()
        manager = SimulationManager(
            settings,
            runtime_dir=tmp_path / "sim-runtime",
            grace_seconds=2.0,
            stop_timeout_seconds=5.0,
        )
        first_run: UUID | None = None
        second_run: UUID | None = None

        async with running_subscriber(settings, mqtt_database.session_factory):
            try:
                first = await manager.start(vehicle_id, "normal", 0.5, seed=1)
                assert first.status == "running", first
                assert first.run_id is not None
                first_run = first.run_id
                await _wait_for_run(mqtt_database, vehicle_id, first_run)

                second = await manager.restart(vehicle_id, "normal", 0.5, seed=2)
                assert second.status == "running", second
                assert second.run_id is not None
                assert second.run_id != first_run
                second_run = second.run_id
                await _wait_for_run(mqtt_database, vehicle_id, second_run)
            finally:
                await manager.shutdown()

        factory = mqtt_database.session_factory
        async with factory() as session:
            observed = set(
                (
                    await session.scalars(
                        select(TelemetryRecord.simulation_run_id)
                        .where(TelemetryRecord.vehicle_id == vehicle_id)
                        .distinct()
                    )
                ).all()
            )
        assert observed == {first_run, second_run}

    run_selector(case())
