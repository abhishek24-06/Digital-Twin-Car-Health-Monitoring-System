"""MQTT-specific domain errors.

These are distinct from the HTTP-facing ``app.core.exceptions`` errors; they
describe problems with MQTT messages and are used to log-and-skip malformed
traffic without crashing the subscriber.
"""


class MQTTParseError(Exception):
    """Base class for MQTT message parse/validation errors."""


class TopicParseError(MQTTParseError):
    """Raised when a topic does not match the expected structure."""


class InvalidMessageError(MQTTParseError):
    """Raised when a payload cannot be decoded or fails schema validation."""
