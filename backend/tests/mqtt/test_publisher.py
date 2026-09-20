"""Publisher topic + payload serialization (no broker required)."""

import json
from datetime import UTC, datetime

from app.core.config import get_settings
from app.mqtt.publisher import MQTTPublisher
from app.mqtt.schemas import StatusMessage, TelemetryData, TelemetryMessage
from app.mqtt.topics import build_status_topic, build_telemetry_topic

VEHICLE_ID = "11111111-2222-4333-8444-555555555555"


def telemetry_message(vehicle_id: str) -> TelemetryMessage:
    return TelemetryMessage(
        schema_version=1,
        event_id="event-pub",
        vehicle_id=vehicle_id,
        timestamp=datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC),
        telemetry=TelemetryData(rpm=2100.0, speed=60.0),
    )


async def test_publish_telemetry_builds_topic_and_json(monkeypatch) -> None:
    publisher = MQTTPublisher(get_settings())
    captured: dict = {}

    async def fake_publish(topic: str, payload: str) -> None:
        captured["topic"] = topic
        captured["payload"] = payload

    monkeypatch.setattr(publisher, "_publish", fake_publish)

    await publisher.publish_telemetry(telemetry_message(VEHICLE_ID))

    assert captured["topic"] == build_telemetry_topic(VEHICLE_ID)
    body = json.loads(captured["payload"])
    assert body["event_id"] == "event-pub"
    assert body["vehicle_id"] == VEHICLE_ID
    assert body["telemetry"]["rpm"] == 2100.0


async def test_publish_status_builds_topic(monkeypatch) -> None:
    publisher = MQTTPublisher(get_settings())
    captured: dict = {}

    async def fake_publish(topic: str, payload: str) -> None:
        captured["topic"] = topic
        captured["payload"] = payload

    monkeypatch.setattr(publisher, "_publish", fake_publish)

    await publisher.publish_status(
        StatusMessage(
            vehicle_id=VEHICLE_ID,
            status="online",
            timestamp=datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC),
        )
    )

    assert captured["topic"] == build_status_topic(VEHICLE_ID)
    body = json.loads(captured["payload"])
    assert body["vehicle_id"] == VEHICLE_ID
    assert body["status"] == "online"
