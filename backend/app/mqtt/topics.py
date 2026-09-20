"""MQTT topic building and parsing.

Topic conventions are centralized here so the simulator, subscriber and any
future publishers agree on the exact format:

    {prefix}/{vehicle_id}/telemetry   -> raw telemetry samples
    {prefix}/{vehicle_id}/status      -> vehicle online/offline status

Parsing functions return ``None`` when a topic does not match the expected
structure instead of raising, which lets the subscriber ignore unrelated
traffic gracefully.
"""

from __future__ import annotations

from uuid import UUID

TELEMETRY_LEVEL = "telemetry"
STATUS_LEVEL = "status"
SEGMENT_SEPARATOR = "/"


def build_telemetry_topic(vehicle_id: UUID, prefix: str = "vehicles") -> str:
    """Return the topic a vehicle publishes telemetry samples to."""
    return SEGMENT_SEPARATOR.join((prefix, str(vehicle_id), TELEMETRY_LEVEL))


def build_status_topic(vehicle_id: UUID, prefix: str = "vehicles") -> str:
    """Return the topic a vehicle publishes status updates to."""
    return SEGMENT_SEPARATOR.join((prefix, str(vehicle_id), STATUS_LEVEL))


def telemetry_subscribe_pattern(prefix: str = "vehicles") -> str:
    """Return the wildcard pattern the subscriber subscribes with."""
    return SEGMENT_SEPARATOR.join((prefix, "+", TELEMETRY_LEVEL))


def parse_telemetry_topic(topic: str, prefix: str = "vehicles") -> UUID | None:
    """Extract the vehicle id from a telemetry topic.

    Returns ``None`` when the topic is not a well-formed telemetry topic for
    the configured prefix.
    """
    return _parse_topic(topic, prefix, TELEMETRY_LEVEL)


def parse_status_topic(topic: str, prefix: str = "vehicles") -> UUID | None:
    """Extract the vehicle id from a status topic (or ``None``)."""
    return _parse_topic(topic, prefix, STATUS_LEVEL)


def _parse_topic(topic: str, prefix: str, last_level: str) -> UUID | None:
    if not topic or topic.startswith("$"):
        return None
    parts = topic.split(SEGMENT_SEPARATOR)
    if len(parts) != 3 or parts[0] != prefix or parts[2] != last_level:
        return None
    if "+" in parts[1] or "#" in parts[1]:
        return None
    try:
        return UUID(parts[1])
    except ValueError:
        return None
