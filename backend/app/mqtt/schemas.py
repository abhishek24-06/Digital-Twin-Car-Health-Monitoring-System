"""MQTT message envelopes.

The telemetry envelope is intentionally versioned so payload format changes
can be signalled without breaking older producers/consumers:

    {
      "schema_version": 1,
      "event_id": "ABC123",
      "vehicle_id": "...",
      "timestamp": "2026-01-01T00:00:00Z",
      "telemetry": { ... }
    }

``timestamp`` is required to be timezone-aware; naive values are rejected.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1


def ensure_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware (e.g. '2026-01-01T00:00:00Z')")
    return value


class TelemetryData(BaseModel):
    """Raw telemetry values, mirroring the REST telemetry schema."""

    model_config = ConfigDict(extra="forbid")

    rpm: float | None = Field(default=None, ge=0, le=10000)
    speed: float | None = Field(default=None, ge=0, le=400)
    engine_load: float | None = Field(default=None, ge=0, le=100)
    coolant_temperature: float | None = Field(default=None, ge=-60, le=200)
    oil_temperature: float | None = Field(default=None, ge=-60, le=200)
    battery_voltage: float | None = Field(default=None, ge=0, le=40)
    fuel_level: float | None = Field(default=None, ge=0, le=100)
    intake_air_temperature: float | None = Field(default=None, ge=-60, le=120)
    throttle_position: float | None = Field(default=None, ge=0, le=100)
    engine_runtime: float | None = Field(default=None, ge=0)
    odometer: float | None = Field(default=None, ge=0)


class TelemetryMessage(BaseModel):
    """A telemetry sample envelope as exchanged over MQTT."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, le=255)
    event_id: str = Field(min_length=1, max_length=64)
    vehicle_id: UUID
    timestamp: datetime
    telemetry: TelemetryData

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_timezone_aware(value)


class StatusMessage(BaseModel):
    """Vehicle online/offline status as exchanged over MQTT."""

    model_config = ConfigDict(extra="forbid")

    vehicle_id: UUID
    status: Literal["online", "offline"]
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_timezone_aware(value)
