"""Simulator MQTT publishing.

Reuses ``app.mqtt.publisher.MQTTPublisher`` verbatim so the simulator and the
subscriber share identical topic and payload conventions.
"""

from app.mqtt.publisher import MQTTPublisher

SimulatorPublisher = MQTTPublisher

__all__ = ["SimulatorPublisher"]
