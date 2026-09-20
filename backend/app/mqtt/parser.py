"""Decode and validate MQTT telemetry payloads.

The parser is deliberately free of broker/DB concerns so it can be unit-tested
in isolation and reused by any consumer.
"""

from __future__ import annotations

import json

from app.mqtt.exceptions import InvalidMessageError, TopicParseError
from app.mqtt.schemas import TelemetryMessage
from app.mqtt.topics import parse_telemetry_topic


class TelemetryMessageParser:
    """Decode a raw MQTT payload into a validated :class:`TelemetryMessage`."""

    def __init__(self, topic_prefix: str = "vehicles") -> None:
        self._topic_prefix = topic_prefix

    def parse(self, topic: str, payload: bytes) -> TelemetryMessage:
        """Parse a telemetry envelope, raising on malformed input.

        Raises:
            TopicParseError: topic is not a well-formed telemetry topic.
            InvalidMessageError: payload cannot be decoded or does not validate.
        """
        vehicle_id = parse_telemetry_topic(topic, self._topic_prefix)
        if vehicle_id is None:
            raise TopicParseError(f"not a telemetry topic: {topic!r}")

        if not payload:
            raise InvalidMessageError("empty payload")

        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidMessageError(f"payload is not valid UTF-8 JSON: {exc}") from exc

        if not isinstance(raw, dict):
            raise InvalidMessageError("payload must be a JSON object")

        try:
            message = TelemetryMessage.model_validate(raw)
        except Exception as exc:
            raise InvalidMessageError(f"payload failed validation: {exc}") from exc

        if message.vehicle_id != vehicle_id:
            raise InvalidMessageError(
                f"envelope vehicle_id does not match topic ({message.vehicle_id} != {vehicle_id})"
            )
        return message
