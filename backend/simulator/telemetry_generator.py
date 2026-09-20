"""Deterministic telemetry generation.

The engine advances a physical vehicle state through the driving-state machine
and derives sensor values from physically plausible rules, optional failure
scenario modifiers, and a seeded RNG so a given seed always reproduces the same
sample sequence.

Physical invariants enforced here:
    - fuel level only ever decreases while the engine runs
    - odometer only ever increases, proportional to speed
    - engine runtime only accumulates while the engine is not OFF
    - battery voltage sits near its running set-point while the engine runs
"""

from __future__ import annotations

import math
import random

from app.mqtt.schemas import TelemetryData
from simulator.config import SimulatorSettings
from simulator.vehicle import NEXT_STATE, DrivingState, VehicleState


class Scenario:
    """Per-scenario physical modifiers."""

    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def coolant_target(self) -> float:
        return 115.0 if self.name == "high_temperature" else 90.0

    @property
    def oil_target(self) -> float:
        return 108.0 if self.name == "high_temperature" else 88.0

    @property
    def running_voltage(self) -> float:
        return 11.9 if self.name == "low_battery" else 13.9

    @property
    def offline_voltage(self) -> float:
        return 11.4 if self.name == "low_battery" else 12.5

    @property
    def load_multiplier(self) -> float:
        return 1.5 if self.name == "high_engine_load" else 1.0

    def clamp_load(self, load: float) -> float:
        return min(load * self.load_multiplier, 100.0)


class SimulationEngine:
    """Directly observable drive-cycle state machine + sensor model."""

    def __init__(self, settings: SimulatorSettings) -> None:
        self._settings = settings
        self._rng = random.Random(settings.seed)
        self._scenario = Scenario(settings.scenario)
        self.state = VehicleState(
            coolant_temperature=25.0,
            oil_temperature=22.0,
            battery_voltage=12.5,
            fuel_level=settings.initial_fuel_level,
            intake_air_temperature=25.0,
            engine_runtime=settings.initial_engine_runtime,
            odometer=settings.initial_odometer,
        )

    def step(self, dt: float) -> TelemetryData:
        """Advance the simulation by ``dt`` seconds and return a sample."""
        state = self.state
        state.state_elapsed += dt
        if state.state_elapsed >= self._phase_duration():
            self._advance_phase()

        update = {
            DrivingState.OFF: self._update_off,
            DrivingState.STARTING: self._update_starting,
            DrivingState.IDLE: self._update_idle,
            DrivingState.ACCELERATING: self._update_accelerating,
            DrivingState.CRUISING: self._update_cruising,
            DrivingState.DECELERATING: self._update_decelerating,
        }[state.state]
        update(dt)

        # Cross-cutting physical progress.
        if state.state != DrivingState.OFF:
            state.engine_runtime += dt
        state.odometer += state.speed / 3600.0 * dt

        self._consume_fuel(dt)
        self._clamp_state()
        return self._build_telemetry()

    # ------------------------------------------------------------------ phases

    def _advance_phase(self) -> None:
        self.state.state_elapsed = 0.0
        self.state.state = NEXT_STATE[self.state.state]

    def _phase_duration(self) -> float:
        return {
            DrivingState.OFF: self._settings.off_seconds,
            DrivingState.STARTING: self._settings.starting_seconds,
            DrivingState.IDLE: self._settings.idle_seconds,
            DrivingState.ACCELERATING: self._settings.accelerating_seconds,
            DrivingState.CRUISING: self._settings.cruising_seconds,
            DrivingState.DECELERATING: self._settings.decelerating_seconds,
        }[self.state.state]

    def _phase_fraction(self) -> float:
        duration = self._phase_duration()
        return min(self.state.state_elapsed / duration, 1.0)

    # ------------------------------------------------------------ sensor model

    def _update_off(self, dt: float) -> None:
        s = self.state
        s.rpm = 0.0
        s.speed = 0.0
        s.throttle_position = 0.0
        s.engine_load = 0.0
        s.battery_voltage = self._drift(
            s.battery_voltage, self._scenario.offline_voltage, 0.002, dt
        )
        s.coolant_temperature = self._drift(s.coolant_temperature, 25.0, 0.01, dt)
        s.oil_temperature = self._drift(s.oil_temperature, 24.0, 0.008, dt)
        s.intake_air_temperature = self._drift(s.intake_air_temperature, 25.0, 0.02, dt)

    def _update_starting(self, dt: float) -> None:
        s = self.state
        progress = self._phase_fraction()
        s.rpm = _smoothstep(progress) * 950.0
        s.speed = 0.0
        s.throttle_position = 1.0
        s.engine_load = 5.0
        s.battery_voltage = self._scenario.offline_voltage - 0.4 + self._noise(0.05)
        s.coolant_temperature = self._drift(s.coolant_temperature, 45.0, 0.05, dt)
        s.oil_temperature = self._drift(s.oil_temperature, 40.0, 0.04, dt)
        s.intake_air_temperature = self._drift(s.intake_air_temperature, 30.0, 0.03, dt)

    def _update_idle(self, dt: float) -> None:
        s = self.state
        s.rpm = self._noise_around(850.0, 25.0)
        s.speed = 0.0
        s.throttle_position = self._noise_around(2.5, 0.6)
        s.engine_load = min(self._scenario.clamp_load(self._noise_around(12.0, 3.0)), 100.0)
        s.battery_voltage = self._charge(s.battery_voltage, self._scenario.running_voltage, dt)
        s.coolant_temperature = self._drift(
            s.coolant_temperature, self._scenario.coolant_target, 0.03, dt
        )
        s.oil_temperature = self._drift(s.oil_temperature, self._scenario.oil_target, 0.02, dt)
        s.intake_air_temperature = self._drift(s.intake_air_temperature, 30.0, 0.03, dt)

    def _update_accelerating(self, dt: float) -> None:
        s = self.state
        eased = _smoothstep(self._phase_fraction())
        target_speed = self._settings.cruise_speed * eased
        s.speed = max(s.speed, target_speed + self._noise(0.4))
        gear_heavier: float = max(target_speed, 1.0)
        s.rpm = 1100.0 + gear_heavier * 22.0 + self._noise(30.0)
        s.throttle_position = max(20.0, self._noise_around(25.0 + 28.0 * eased, 4.0))
        s.engine_load = self._scenario.clamp_load(self._noise_around(45.0 + 40.0 * eased, 6.0))
        s.battery_voltage = self._charge(s.battery_voltage, self._scenario.running_voltage, dt)
        s.coolant_temperature = self._drift(
            s.coolant_temperature, self._scenario.coolant_target, 0.05, dt
        )
        s.oil_temperature = self._drift(s.oil_temperature, self._scenario.oil_target, 0.03, dt)
        s.intake_air_temperature = self._drift(s.intake_air_temperature, 32.0, 0.04, dt)

    def _update_cruising(self, dt: float) -> None:
        s = self.state
        s.speed = self._noise_around(self._settings.cruise_speed, 1.5)
        s.rpm = self._noise_around(2000.0 + self._settings.cruise_speed * 2.0, 60.0)
        s.throttle_position = self._noise_around(18.0, 3.0)
        s.engine_load = self._scenario.clamp_load(self._noise_around(32.0, 5.0))
        s.battery_voltage = self._charge(s.battery_voltage, self._scenario.running_voltage, dt)
        s.coolant_temperature = self._drift(
            s.coolant_temperature, self._scenario.coolant_target, 0.04, dt
        )
        s.oil_temperature = self._drift(s.oil_temperature, self._scenario.oil_target, 0.02, dt)
        s.intake_air_temperature = self._drift(s.intake_air_temperature, 34.0, 0.04, dt)

    def _update_decelerating(self, dt: float) -> None:
        s = self.state
        eased = _smoothstep(self._phase_fraction())
        remaining = 1.0 - eased
        s.speed = max(0.0, self._settings.cruise_speed * remaining + self._noise(0.5))
        s.rpm = 950.0 + s.speed * 15.0 + self._noise(25.0)
        s.throttle_position = max(0.0, 3.0 - 3.0 * eased)
        s.engine_load = self._scenario.clamp_load(self._noise_around(10.0 + 15.0 * eased, 3.0))
        s.battery_voltage = self._charge(s.battery_voltage, self._scenario.running_voltage, dt)
        s.coolant_temperature = self._drift(
            s.coolant_temperature, self._scenario.coolant_target, 0.03, dt
        )
        s.oil_temperature = self._drift(s.oil_temperature, self._scenario.oil_target, 0.02, dt)
        s.intake_air_temperature = self._drift(s.intake_air_temperature, 32.0, 0.03, dt)

    # ------------------------------------------------------------ cross-cutting

    def _consume_fuel(self, dt: float) -> None:
        if self.state.state == DrivingState.OFF:
            return
        # Approximate %/hour consumption rising with engine load.
        consumption_per_hour = 0.35 + self.state.engine_load * 0.015
        self.state.fuel_level = max(0.0, self.state.fuel_level - consumption_per_hour / 3600.0 * dt)

    def _clamp_state(self) -> None:
        s = self.state
        s.fuel_level = min(max(s.fuel_level, 0.0), 100.0)
        s.battery_voltage = min(max(s.battery_voltage, 0.0), 30.0)
        s.speed = max(s.speed, 0.0)
        s.rpm = max(s.rpm, 0.0)
        s.engine_load = min(max(s.engine_load, 0.0), 100.0)
        s.throttle_position = min(max(s.throttle_position, 0.0), 100.0)

    def _build_telemetry(self) -> TelemetryData:
        s = self.state
        return TelemetryData(
            rpm=_round1(s.rpm),
            speed=_round1(s.speed),
            engine_load=_round1(s.engine_load),
            coolant_temperature=_round1(s.coolant_temperature),
            oil_temperature=_round1(s.oil_temperature),
            battery_voltage=_round2(s.battery_voltage),
            fuel_level=_round2(s.fuel_level),
            intake_air_temperature=_round1(s.intake_air_temperature),
            throttle_position=_round1(s.throttle_position),
            engine_runtime=_round1(s.engine_runtime),
            odometer=_round3(s.odometer),
        )

    # --------------------------------------------------------------- helpers

    def _noise(self, sigma: float) -> float:
        return self._rng.gauss(0.0, sigma)

    def _noise_around(self, value: float, sigma: float) -> float:
        return value + self._noise(sigma)

    @staticmethod
    def _drift(current: float, target: float, rate: float, dt: float) -> float:
        """Exponentially approach ``target`` at ``rate`` per second."""
        return current + (target - current) * (1.0 - math.exp(-rate * dt))

    def _charge(self, current: float, target: float, dt: float) -> float:
        charged = self._drift(current, target, 0.02, dt)
        return charged + self._noise(0.05)


def _smoothstep(progress: float) -> float:
    p = min(max(progress, 0.0), 1.0)
    return p * p * (3.0 - 2.0 * p)


def _round1(value: float) -> float:
    return round(value, 1)


def _round2(value: float) -> float:
    return round(value, 2)


def _round3(value: float) -> float:
    return round(value, 3)
