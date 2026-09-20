"""Simulator configuration.

Prefixed with ``SIMULATOR_`` in the environment (e.g. ``SIMULATOR_VEHICLE_ID``);
MQTT connection fields reuse the platform-wide ``MQTT_*`` names so the simulator
can call the same client factory as the subscriber.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

ScenarioName = Literal["normal", "high_temperature", "low_battery", "high_engine_load"]


class SimulatorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # Vehicle identity (required).
    vehicle_id: UUID = Field(validation_alias="SIMULATOR_VEHICLE_ID")

    # Simulation control.
    scenario: ScenarioName = Field(default="normal", validation_alias="SIMULATOR_SCENARIO")
    interval_seconds: float = Field(
        default=1.0, gt=0, validation_alias="SIMULATOR_INTERVAL_SECONDS"
    )
    seed: int = Field(default=42, validation_alias="SIMULATOR_SEED")

    # Initial physical state.
    initial_odometer: float = Field(
        default=45231.7, ge=0, validation_alias="SIMULATOR_INITIAL_ODOMETER"
    )
    initial_fuel_level: float = Field(
        default=75.0, ge=0, le=100, validation_alias="SIMULATOR_INITIAL_FUEL_LEVEL"
    )
    initial_engine_runtime: float = Field(
        default=0.0, ge=0, validation_alias="SIMULATOR_INITIAL_ENGINE_RUNTIME"
    )

    # Driving-phase durations (seconds).
    off_seconds: float = Field(default=2.0, gt=0, validation_alias="SIMULATOR_OFF_SECONDS")
    starting_seconds: float = Field(
        default=3.0, gt=0, validation_alias="SIMULATOR_STARTING_SECONDS"
    )
    idle_seconds: float = Field(default=10.0, gt=0, validation_alias="SIMULATOR_IDLE_SECONDS")
    accelerating_seconds: float = Field(
        default=15.0, gt=0, validation_alias="SIMULATOR_ACCELERATING_SECONDS"
    )
    cruising_seconds: float = Field(
        default=30.0, gt=0, validation_alias="SIMULATOR_CRUISING_SECONDS"
    )
    decelerating_seconds: float = Field(
        default=10.0, gt=0, validation_alias="SIMULATOR_DECELERATING_SECONDS"
    )
    cruise_speed: float = Field(default=60.0, gt=0, validation_alias="SIMULATOR_CRUISE_SPEED")

    # MQTT connection (shared platform-wide naming).
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_client_id: str = "digital-twin-simulator"
    mqtt_keepalive: int = 60
    mqtt_qos: int = 1
    mqtt_topic_prefix: str = "vehicles"
    mqtt_reconnect_max_seconds: float = 30.0

    debug: bool = False

    @field_validator("scenario")
    @classmethod
    def _validate_scenario(cls, value: str) -> str:
        allowed = {"normal", "high_temperature", "low_battery", "high_engine_load"}
        if value not in allowed:
            raise ValueError(f"scenario must be one of {sorted(allowed)}")
        return value


@lru_cache
def get_simulator_settings() -> SimulatorSettings:
    return SimulatorSettings()
