"""Topic building/parsing conventions (single source of truth)."""

from uuid import UUID, uuid4

from app.mqtt.topics import (
    TELEMETRY_LEVEL,
    build_status_topic,
    build_telemetry_topic,
    parse_status_topic,
    parse_telemetry_topic,
    telemetry_subscribe_pattern,
)


def test_build_and_parse_telemetry_topic_round_trip() -> None:
    vehicle_id = uuid4()
    topic = build_telemetry_topic(vehicle_id)
    assert topic == f"vehicles/{vehicle_id}/telemetry"
    assert parse_telemetry_topic(topic) == vehicle_id


def test_build_and_parse_status_topic_round_trip() -> None:
    vehicle_id = uuid4()
    topic = build_status_topic(vehicle_id)
    assert topic == f"vehicles/{vehicle_id}/status"
    assert parse_status_topic(topic) == vehicle_id


def test_custom_prefix_round_trip() -> None:
    vehicle_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, prefix="fleet")
    assert topic == f"fleet/{vehicle_id}/telemetry"
    assert parse_telemetry_topic(topic, prefix="fleet") == vehicle_id


def test_subscribe_pattern_matches_built_topic() -> None:
    pattern = telemetry_subscribe_pattern()
    topic = build_telemetry_topic(uuid4())
    parts = pattern.split("/")
    topic_parts = topic.split("/")
    assert len(parts) == len(topic_parts) == 3
    assert parts[0] == topic_parts[0] == "vehicles"
    assert parts[1] == "+"
    assert parts[2] == topic_parts[2] == TELEMETRY_LEVEL


def test_parse_rejects_wrong_last_level() -> None:
    assert parse_telemetry_topic(f"vehicles/{uuid4()}/status") is None
    assert parse_status_topic(f"vehicles/{uuid4()}/telemetry") is None


def test_parse_rejects_wrong_prefix() -> None:
    assert parse_telemetry_topic(f"fleet/{uuid4()}/telemetry") is None


def test_parse_rejects_malformed() -> None:
    assert parse_telemetry_topic("") is None
    assert parse_telemetry_topic("vehicles") is None
    assert parse_telemetry_topic("vehicles/telemetry") is None
    assert parse_telemetry_topic("vehicles/abc/telemetry") is None
    assert parse_telemetry_topic("vehicles/+/telemetry") is None
    assert parse_telemetry_topic("vehicles/#/telemetry") is None
    assert parse_telemetry_topic("a/b/c/d") is None
    assert parse_telemetry_topic("$SYS/broker/load") is None


def test_parse_accepts_uuid_forms() -> None:
    raw = uuid4().hex
    topic = f"vehicles/{raw}/telemetry"
    assert parse_telemetry_topic(topic) == UUID(raw)
