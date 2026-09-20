from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TelemetryCreate(BaseModel):
    """A single raw telemetry sample submitted for a vehicle."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    rpm: float | None = Field(default=None, ge=0)
    speed: float | None = Field(default=None, ge=0)
    engine_load: float | None = Field(default=None, ge=0, le=100)
    coolant_temperature: float | None = Field(default=None, ge=-60, le=200)
    oil_temperature: float | None = Field(default=None, ge=-60, le=200)
    battery_voltage: float | None = Field(default=None, ge=0, le=40)
    fuel_level: float | None = Field(default=None, ge=0, le=100)
    intake_air_temperature: float | None = Field(default=None, ge=-60, le=120)
    throttle_position: float | None = Field(default=None, ge=0, le=100)
    engine_runtime: float | None = Field(default=None, ge=0)
    odometer: float | None = Field(default=None, ge=0)
    raw_payload: dict[str, Any] | None = None
    source_event_id: str | None = Field(default=None, min_length=1, max_length=64)


class TelemetryResponse(BaseModel):
    id: UUID
    vehicle_id: UUID
    timestamp: datetime
    rpm: float | None
    speed: float | None
    engine_load: float | None
    coolant_temperature: float | None
    oil_temperature: float | None
    battery_voltage: float | None
    fuel_level: float | None
    intake_air_temperature: float | None
    throttle_position: float | None
    engine_runtime: float | None
    odometer: float | None
    raw_payload: dict[str, Any] | None
    source_event_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
