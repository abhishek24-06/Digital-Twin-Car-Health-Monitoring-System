"""Subscriber handling: valid / duplicate / malformed / unknown-vehicle messages.

Telemetry flows through the app's real service + repository layers and into the
test database; only the broker is absent (messages are constructed directly).
"""

import asyncio
import json
from uuid import uuid4

import aiomqtt
from sqlalchemy import func, select

from app.core.config import get_settings
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
