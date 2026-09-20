"""Parser behavior: decode + validate MQTT payloads."""

import json
from uuid import uuid4

import pytest

from app.mqtt.exceptions import InvalidMessageError, TopicParseError
from app.mqtt.parser import TelemetryMessageParser
from app.mqtt.topics import build_telemetry_topic

VEHICLE = "11111111-2222-4333-8444-555555555555"


def envelope(vehicle_id: str = VEHICLE, **overrides):
    payload = {
        "schema_version": 1,
        "event_id": "abc123",
        "vehicle_id": vehicle_id,
        "timestamp": "2026-09-20T10:00:00+00:00",
        "telemetry": {"rpm": 2145.0, "speed": 61.0, "battery_voltage": 13.9},
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


@pytest.fixture
def parser() -> TelemetryMessageParser:
    return TelemetryMessageParser()


def test_parse_valid_payload(parser: TelemetryMessageParser) -> None:
    topic = build_telemetry_topic(VEHICLE)
    message = parser.parse(topic, envelope())
    assert message.event_id == "abc123"
    assert str(message.vehicle_id) == VEHICLE


def test_parse_non_telemetry_topic_raises(parser: TelemetryMessageParser) -> None:
    with pytest.raises(TopicParseError):
        parser.parse("vehicles/abc/status", envelope())


def test_parse_invalid_json_raises(parser: TelemetryMessageParser) -> None:
    with pytest.raises(InvalidMessageError):
        parser.parse(build_telemetry_topic(VEHICLE), b"not-json")


def test_parse_json_list_raises(parser: TelemetryMessageParser) -> None:
    with pytest.raises(InvalidMessageError):
        parser.parse(build_telemetry_topic(VEHICLE), b"[1,2,3]")


def test_parse_empty_payload_raises(parser: TelemetryMessageParser) -> None:
    with pytest.raises(InvalidMessageError):
        parser.parse(build_telemetry_topic(VEHICLE), b"")


def test_parse_invalid_schema_raises(parser: TelemetryMessageParser) -> None:
    with pytest.raises(InvalidMessageError):
        parser.parse(build_telemetry_topic(VEHICLE), envelope(schema_version=999))


def test_parse_naive_timestamp_raises(parser: TelemetryMessageParser) -> None:
    bad = envelope(timestamp="2026-09-20T10:00:00")
    with pytest.raises(InvalidMessageError, match="timezone-aware"):
        parser.parse(build_telemetry_topic(VEHICLE), bad)


def test_parse_vehicle_id_mismatch_raises(parser: TelemetryMessageParser) -> None:
    other = uuid4()
    topic = build_telemetry_topic(other)
    with pytest.raises(InvalidMessageError, match="does not match topic"):
        parser.parse(topic, envelope())


def test_parse_unknown_fields_rejected(parser: TelemetryMessageParser) -> None:
    topic = build_telemetry_topic(VEHICLE)
    raw = json.loads(envelope().decode())
    raw["telemetry"]["ghost_sensor"] = 1.0
    with pytest.raises(InvalidMessageError):
        parser.parse(topic, json.dumps(raw).encode())
