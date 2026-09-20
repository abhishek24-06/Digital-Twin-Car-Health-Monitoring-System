"""Vehicle simulation state and the driving-state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DrivingState(StrEnum):
    """Discrete operating modes the simulated vehicle cycles through."""

    OFF = "off"
    STARTING = "starting"
    IDLE = "idle"
    ACCELERATING = "accelerating"
    CRUISING = "cruising"
    DECELERATING = "decelerating"


@dataclass
class VehicleState:
    """Mutable physical state of the simulated vehicle."""

    state: DrivingState = DrivingState.OFF
    state_elapsed: float = 0.0
    rpm: float = 0.0
    speed: float = 0.0  # km/h
    throttle_position: float = 0.0  # percent
    engine_load: float = 0.0  # percent
    coolant_temperature: float = 20.0  # C
    oil_temperature: float = 20.0  # C
    battery_voltage: float = 12.5  # V
    fuel_level: float = 75.0  # percent
    intake_air_temperature: float = 25.0  # C
    engine_runtime: float = 0.0  # seconds
    odometer: float = 0.0  # km


# Next state after each driving state completes its phase. The engine runs
# through STARTING -> IDLE -> ACCELERATING -> CRUISING -> DECELERATING -> IDLE
# and the loop repeats; OFF only occurs once at startup.
NEXT_STATE: dict[DrivingState, DrivingState] = {
    DrivingState.OFF: DrivingState.STARTING,
    DrivingState.STARTING: DrivingState.IDLE,
    DrivingState.IDLE: DrivingState.ACCELERATING,
    DrivingState.ACCELERATING: DrivingState.CRUISING,
    DrivingState.CRUISING: DrivingState.DECELERATING,
    DrivingState.DECELERATING: DrivingState.IDLE,
}
