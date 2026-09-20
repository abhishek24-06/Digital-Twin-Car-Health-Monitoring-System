"""SimulatorSettings: env mapping, required fields, scenario validation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from simulator.config import SimulatorSettings


def test_requires_vehicle_id() -> None:
    with pytest.raises(ValidationError):
        SimulatorSettings()


def test_reads_simulator_env_variables(monkeypatch) -> None:
    vehicle_id = uuid4()
    monkeypatch.setenv("SIMULATOR_VEHICLE_ID", str(vehicle_id))
    monkeypatch.setenv("SIMULATOR_INTERVAL_SECONDS", "0.5")
    monkeypatch.setenv("SIMULATOR_SCENARIO", "low_battery")
    monkeypatch.setenv("SIMULATOR_SEED", "7")
    monkeypatch.setenv("SIMULATOR_CRUISE_SPEED", "80")

    settings = SimulatorSettings()

    assert settings.vehicle_id == vehicle_id
    assert settings.interval_seconds == 0.5
    assert settings.scenario == "low_battery"
    assert settings.seed == 7
    assert settings.cruise_speed == 80.0
    assert settings.mqtt_broker_host == "localhost"


def test_defaults_apply() -> None:
    settings = SimulatorSettings(vehicle_id=uuid4())
    assert settings.interval_seconds == 1.0
    assert settings.scenario == "normal"
    assert settings.seed == 42
    assert settings.mqtt_topic_prefix == "vehicles"


def test_invalid_scenario_rejected() -> None:
    with pytest.raises(ValidationError, match="scenario"):
        SimulatorSettings(vehicle_id=uuid4(), scenario="greenhouse")


def test_accepts_keyword_vehicle_id() -> None:
    vehicle_id = uuid4()
    settings = SimulatorSettings(vehicle_id=vehicle_id)
    assert settings.vehicle_id == vehicle_id
