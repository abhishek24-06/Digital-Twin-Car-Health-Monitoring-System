"""Subscriber handling: valid / duplicate / malformed / unknown-vehicle messages.

Telemetry flows through the app's real service + repository layers and into the
test database; only the broker is absent (messages are constructed directly).
"""

import asyncio
import json
from datetime import datetime
from uuid import uuid4

import aiomqtt
from sqlalchemy import event, func, select

from app.core.config import get_settings
from app.core.database import get_engine
from app.models.telemetry import TelemetryRecord
from app.mqtt.subscriber import MQTTSubscriber


def mqtt_message(topic: str, payload: bytes) -> aiomqtt.Message:
    return aiomqtt.Message(
        topic=aiomqtt.Topic(topic),
        payload=payload,
        qos=1,
        retain=False,
        mid=0,
        properties=None,
    )


def envelope_json(vehicle_id: str, event_id: str = "event-1") -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "event_id": event_id,
            "vehicle_id": vehicle_id,
            "timestamp": "2026-09-20T10:00:00+00:00",
            "telemetry": {"rpm": 2145.0, "speed": 61.0, "battery_voltage": 13.9},
        }
    ).encode("utf-8")


async def _record_count(session_factory) -> int:
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(TelemetryRecord))
    return int(total or 0)


async def test_valid_message_persisted(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]

    await subscriber._handle_message(
        mqtt_message(f"vehicles/{vehicle_id}/telemetry", envelope_json(vehicle_id))
    )

    assert await _record_count(session_factory) == 1
    async with session_factory() as session:
        record = await session.scalar(select(TelemetryRecord))
        assert str(record.vehicle_id) == vehicle_id
        assert record.source_event_id == "event-1"
        assert record.rpm == 2145.0
        assert record.raw_payload["event_id"] == "event-1"
        # Legacy envelope carries no run identity: NULL, never fabricated.
        assert record.simulation_run_id is None


async def test_run_id_persisted_from_envelope(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]
    run_id = uuid4()
    payload = json.dumps(
        {
            "schema_version": 2,
            "event_id": "run-1",
            "vehicle_id": vehicle_id,
            "simulation_run_id": str(run_id),
            "timestamp": "2026-09-20T10:00:00+00:00",
            "telemetry": {"rpm": 2100.0},
        }
    ).encode()

    await subscriber._handle_message(mqtt_message(f"vehicles/{vehicle_id}/telemetry", payload))

    async with session_factory() as session:
        record = await session.scalar(select(TelemetryRecord))
        assert record.simulation_run_id == run_id
        assert record.raw_payload["simulation_run_id"] == str(run_id)


async def test_run_id_persisted_and_dropped_on_stop(session_factory, sample_vehicle) -> None:
    """Samples from run A and run B coexist; legacy samples stay NULL."""
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]
    run_a, run_b = uuid4(), uuid4()
    topic = f"vehicles/{vehicle_id}/telemetry"

    def run_envelope(event_id: str, run: uuid4) -> bytes:
        return json.dumps(
            {
                "schema_version": 2,
                "event_id": event_id,
                "vehicle_id": vehicle_id,
                "simulation_run_id": str(run),
                "timestamp": "2026-09-20T10:00:00+00:00",
                "telemetry": {"rpm": 2100.0},
            }
        ).encode()

    await subscriber._handle_message(mqtt_message(topic, run_envelope("a-1", run_a)))
    await subscriber._handle_message(mqtt_message(topic, run_envelope("b-1", run_b)))
    await subscriber._handle_message(mqtt_message(topic, envelope_json(vehicle_id, "legacy-1")))

    assert await _record_count(session_factory) == 3
    async with session_factory() as session:
        rows = (await session.scalars(select(TelemetryRecord))).all()
        by_event = {row.source_event_id: row for row in rows}
        assert by_event["a-1"].simulation_run_id == run_a
        assert by_event["b-1"].simulation_run_id == run_b
        assert by_event["legacy-1"].simulation_run_id is None


async def test_duplicate_message_skipped(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]
    topic = f"vehicles/{vehicle_id}/telemetry"
    payload = envelope_json(vehicle_id)

    await subscriber._handle_message(mqtt_message(topic, payload))
    await subscriber._handle_message(mqtt_message(topic, payload))

    assert await _record_count(session_factory) == 1


async def test_different_event_id_persisted_twice(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]
    topic = f"vehicles/{vehicle_id}/telemetry"

    await subscriber._handle_message(mqtt_message(topic, envelope_json(vehicle_id, "event-1")))
    await subscriber._handle_message(mqtt_message(topic, envelope_json(vehicle_id, "event-2")))

    assert await _record_count(session_factory) == 2


async def test_invalid_json_skipped(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]

    await subscriber._handle_message(mqtt_message(f"vehicles/{vehicle_id}/telemetry", b"not-json"))

    assert await _record_count(session_factory) == 0


async def test_invalid_envelope_skipped(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]

    await subscriber._handle_message(mqtt_message(f"vehicles/{vehicle_id}/telemetry", b"{}"))

    assert await _record_count(session_factory) == 0


async def test_vehicle_id_mismatch_skipped(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    topic_vehicle = sample_vehicle["id"]
    other = str(uuid4())
    payload = json.dumps(
        {
            "schema_version": 1,
            "event_id": "event-x",
            "vehicle_id": other,
            "timestamp": "2026-09-20T10:00:00+00:00",
            "telemetry": {"rpm": 1000.0},
        }
    ).encode()

    await subscriber._handle_message(mqtt_message(f"vehicles/{topic_vehicle}/telemetry", payload))

    assert await _record_count(session_factory) == 0


async def test_unknown_vehicle_skipped(session_factory) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = str(uuid4())
    payload = json.dumps(
        {
            "schema_version": 1,
            "event_id": "event-unknown",
            "vehicle_id": vehicle_id,
            "timestamp": "2026-09-20T10:00:00+00:00",
            "telemetry": {"rpm": 1000.0},
        }
    ).encode()

    await subscriber._handle_message(mqtt_message(f"vehicles/{vehicle_id}/telemetry", payload))

    assert await _record_count(session_factory) == 0


async def test_non_telemetry_topic_ignored(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]

    await subscriber._handle_message(
        mqtt_message(f"vehicles/{vehicle_id}/status", envelope_json(vehicle_id))
    )

    assert await _record_count(session_factory) == 0


async def test_run_forever_returns_when_stop_set(session_factory) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    stop_event = asyncio.Event()
    stop_event.set()
    await asyncio.wait_for(subscriber.run_forever(stop_event), timeout=2.0)


# --- Batched persistence (ingestion throughput regression) ------------------
#
# Root cause of the live "stale telemetry / no_data" incident: the subscriber
# persisted one message per transaction (one existence SELECT, one duplicate
# SELECT, one INSERT, one refresh SELECT, one COMMIT). Over a high-latency
# database a serial loop cannot keep up with several 1 Hz publishers, so the
# in-memory backlog grew and every sample landed already older than the health
# analysis window. These tests pin the batched behaviour that fixes it.


async def _count_insert_statements(session_factory, coro) -> tuple[int, int]:
    """Run ``coro`` while counting INSERTs into ``telemetry_records``.

    Returns ``(insert_statements, rows)``. Pre-fix, N messages produced N INSERT
    statements; the fix must produce a single multi-row statement.
    """
    statements: list[str] = []
    engine = get_engine()

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if "INSERT INTO telemetry_records" in statement:
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        await coro
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)

    return len(statements), await _record_count(session_factory)


async def test_batch_flush_uses_a_single_insert_statement(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]
    topic = f"vehicles/{vehicle_id}/telemetry"
    messages = [mqtt_message(topic, envelope_json(vehicle_id, f"stmt-{i}")) for i in range(25)]

    insert_statements, rows = await _count_insert_statements(
        session_factory, subscriber._flush_batch(messages)
    )

    assert rows == 25
    assert insert_statements == 1, (
        f"expected one batched INSERT for 25 messages, saw {insert_statements}"
    )


async def test_batch_flush_persists_timestamp_verbatim(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]
    topic = f"vehicles/{vehicle_id}/telemetry"

    await subscriber._flush_batch([mqtt_message(topic, envelope_json(vehicle_id, "ts-1"))])

    async with session_factory() as session:
        record = await session.scalar(select(TelemetryRecord))
    assert record.timestamp == datetime.fromisoformat("2026-09-20T10:00:00+00:00")


async def test_batch_flush_dedupes_duplicate_events(session_factory, sample_vehicle) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    vehicle_id = sample_vehicle["id"]
    topic = f"vehicles/{vehicle_id}/telemetry"
    payload = envelope_json(vehicle_id, "same-event")

    await subscriber._flush_batch([mqtt_message(topic, payload), mqtt_message(topic, payload)])

    assert await _record_count(session_factory) == 1


async def test_batch_flush_keeps_known_vehicle_and_drops_unknown(
    session_factory, sample_vehicle
) -> None:
    subscriber = MQTTSubscriber(get_settings(), session_factory)
    known = sample_vehicle["id"]
    unknown = str(uuid4())

    await subscriber._flush_batch(
        [
            mqtt_message(f"vehicles/{known}/telemetry", envelope_json(known, "k1")),
            mqtt_message(f"vehicles/{unknown}/telemetry", envelope_json(unknown, "u1")),
        ]
    )

    assert await _record_count(session_factory) == 1
    async with session_factory() as session:
        record = await session.scalar(select(TelemetryRecord))
    assert str(record.vehicle_id) == known
