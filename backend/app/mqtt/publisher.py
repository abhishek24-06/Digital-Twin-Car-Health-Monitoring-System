"""Long-lived MQTT publisher used by the simulator and any future producers.

The publisher serializes validated envelopes to JSON and publishes with
QoS 1 and ``retain=False`` so every telemetry sample is delivered and old
samples never replay to late subscribers.
"""

from __future__ import annotations

from typing import Any

from app.mqtt.client import MQTTConnectionSettings, create_mqtt_client
from app.mqtt.schemas import StatusMessage, TelemetryMessage
from app.mqtt.topics import build_status_topic, build_telemetry_topic


class MQTTPublisher:
    """Publishes messages on a single long-lived connection."""

    def __init__(self, settings: MQTTConnectionSettings) -> None:
        self._settings = settings
        self._client = None

    async def __aenter__(self) -> MQTTPublisher:
        self._client = create_mqtt_client(self._settings)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        assert self._client is not None
        await self._client.__aexit__(*exc_info)
        self._client = None

    async def publish_telemetry(self, message: TelemetryMessage) -> None:
        await self._publish(
            build_telemetry_topic(message.vehicle_id, self._settings.mqtt_topic_prefix),
            message.model_dump_json(),
        )

    async def publish_status(self, message: StatusMessage) -> None:
        await self._publish(
            build_status_topic(message.vehicle_id, self._settings.mqtt_topic_prefix),
            message.model_dump_json(),
        )

    async def _publish(self, topic: str, payload: str) -> None:
        assert self._client is not None
        await self._client.publish(
            topic,
            payload=payload,
            qos=self._settings.mqtt_qos,
            retain=False,
        )
