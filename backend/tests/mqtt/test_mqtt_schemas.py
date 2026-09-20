"""MQTT envelope schema validation (ranges, timezone, unknown fields)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.mqtt.schemas import StatusMessage, TelemetryData, TelemetryMessage


def telemetry_kwargs():
    return {
        "schema_version": 1,
        "event_id": "event-123",
        "vehicle_id": "11111111-2222-4333-8444-555555555555",
        "timestamp": datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC),
        "telemetry": {"rpm": 2145.0, "speed": 61.0, "battery_voltage": 13.9},
    }


def test_valid_telemetry_message_parses() -> None:
    message = TelemetryMessage.model_validate(telemetry_kwargs())
    assert message.event_id == "event-123"
    assert message.telemetry.rpm == 2145.0


def test_missing_required_fields_rejected() -> None:
    kwargs = telemetry_kwargs()
    del kwargs["telemetry"]
    with pytest.raises(ValidationError):
        TelemetryMessage.model_validate(kwargs)


def test_unknown_envelope_field_rejected() -> None:
    kwargs = telemetry_kwargs()
    kwargs["extra"] = True
    with pytest.raises(ValidationError):
        TelemetryMessage.model_validate(kwargs)


def test_unknown_telemetry_field_rejected() -> None:
    data = {"rpm": 1000.0, "not_a_sensor": 42.0}
    with pytest.raises(ValidationError):
        TelemetryData.model_validate(data)


def test_naive_timestamp_rejected() -> None:
    kwargs = telemetry_kwargs()
    kwargs["timestamp"] = datetime(2026, 9, 20, 10, 0, 0)
    with pytest.raises(ValidationError, match="timezone-aware"):
        TelemetryMessage.model_validate(kwargs)


def test_naive_status_timestamp_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        StatusMessage.model_validate(
            {
                "vehicle_id": "11111111-2222-4333-8444-555555555555",
                "status": "online",
                "timestamp": datetime(2026, 9, 20, 10, 0, 0),
            }
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("rpm", -1),
        ("rpm", 10001),
        ("speed", -0.1),
        ("speed", 401),
        ("engine_load", 101),
        ("coolant_temperature", -61),
        ("coolant_temperature", 201),
        ("oil_temperature", 201),
        ("battery_voltage", 41),
        ("fuel_level", 101),
        ("fuel_level", -1),
        ("intake_air_temperature", 121),
        ("throttle_position", 101),
    ],
)
def test_out_of_range_telemetry_values_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        TelemetryData.model_validate({field: value})


def test_valid_status_payload() -> None:
    status = StatusMessage.model_validate(
        {
            "vehicle_id": "11111111-2222-4333-8444-555555555555",
            "status": "online",
            "timestamp": datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC),
        }
    )
    assert status.status == "online"


def test_invalid_status_value_rejected() -> None:
    with pytest.raises(ValidationError):
        StatusMessage.model_validate(
            {
                "vehicle_id": "11111111-2222-4333-8444-555555555555",
                "status": "rebooting",
                "timestamp": datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC),
            }
        )
