"""Determinism, state-machine and physical invariants of the simulator."""

import pytest

from simulator.config import SimulatorSettings
from simulator.telemetry_generator import SimulationEngine
from simulator.vehicle import DrivingState

DEMO_VEHICLE = "11111111-2222-4333-8444-555555555555"


def make_settings(**overrides) -> SimulatorSettings:
    values = {
        "vehicle_id": DEMO_VEHICLE,
        "seed": 42,
        "interval_seconds": 1.0,
    }
    values.update(overrides)
    return SimulatorSettings(**values)


def run_steps(engine: SimulationEngine, steps: int, dt: float = 1.0):
    return [engine.step(dt) for _ in range(steps)]


def run_states(engine: SimulationEngine, steps: int, dt: float = 1.0):
    output = []
    for _ in range(steps):
        engine.step(dt)
        output.append(engine.state)
    return output


def test_same_seed_is_deterministic() -> None:
    engine_a = SimulationEngine(make_settings(seed=42))
    engine_b = SimulationEngine(make_settings(seed=42))

    expected = run_steps(engine_a, 120)
    actual = run_steps(engine_b, 120)

    assert expected == actual


def test_different_seed_differs() -> None:
    engine_a = SimulationEngine(make_settings(seed=1))
    engine_b = SimulationEngine(make_settings(seed=2))

    assert run_steps(engine_a, 200) != run_steps(engine_b, 200)


def test_state_machine_follows_expected_cycle() -> None:
    engine = SimulationEngine(make_settings())
    states: list[str] = [engine.state.state]

    for _ in range(60):
        engine.step(10.0)
        states.append(engine.state.state)

    # Each 10s step crosses several phase boundaries; the engine must always
    # be in a legal driving state and never return to OFF.
    assert DrivingState.OFF in states  # initial OFF phase
    ordered = [
        DrivingState.STARTING,
        DrivingState.IDLE,
        DrivingState.ACCELERATING,
        DrivingState.CRUISING,
        DrivingState.DECELERATING,
    ]
    for state in ordered:
        assert state in states


def test_initial_phase_is_off_then_starting() -> None:
    engine = SimulationEngine(make_settings())
    engine.step(0.1)
    assert engine.state.state == DrivingState.OFF
    # Run past the OFF phase.
    for _ in range(100):
        engine.step(1.0)
        if engine.state.state == DrivingState.STARTING:
            return
    pytest.fail("engine never left OFF")


def test_fuel_only_decreases_while_running() -> None:
    engine = SimulationEngine(make_settings(initial_fuel_level=80.0))
    previous = 80.0
    decreased = False
    for _ in range(400):
        engine.step(1.0)
        sample = engine.state
        if sample.state != DrivingState.OFF:
            assert sample.fuel_level <= previous + 1e-9
            if sample.fuel_level < previous - 1e-9:
                decreased = True
        previous = sample.fuel_level
    assert decreased


def test_odometer_only_increases_with_speed() -> None:
    engine = SimulationEngine(make_settings())
    previous = engine.state.odometer
    moved = False
    for _ in range(300):
        engine.step(1.0)
        assert engine.state.odometer >= previous - 1e-9
        if engine.state.odometer > previous + 1e-9:
            moved = True
        previous = engine.state.odometer
    assert moved


def test_engine_runtime_does_not_accumulate_while_off() -> None:
    engine = SimulationEngine(make_settings(initial_engine_runtime=100.0))
    runtime_while_off = engine.state.engine_runtime
    for _ in range(int(engine._settings.off_seconds) + 2):
        engine.step(0.5)
        if engine.state.state == DrivingState.OFF:
            assert engine.state.engine_runtime == pytest.approx(runtime_while_off)


def test_samples_validate_against_schema() -> None:
    engine = SimulationEngine(make_settings())
    for sample in run_steps(engine, 300):
        sample.model_validate(sample)  # no exception means valid + in range


def test_samples_are_timestamped_and_typed() -> None:
    engine = SimulationEngine(make_settings())
    sample = engine.step(1.0)
    assert sample.rpm >= 0.0
    assert sample.battery_voltage >= 0.0
    assert 0.0 <= sample.fuel_level <= 100.0


def test_high_temperature_scenario_raises_coolant() -> None:
    hot = SimulationEngine(make_settings(scenario="high_temperature"))
    normal = SimulationEngine(make_settings(scenario="normal"))

    hot_samples = run_steps(hot, 600)
    normal_samples = run_steps(normal, 600)

    hot_peak = max(s.coolant_temperature for s in hot_samples)
    normal_peak = max(s.coolant_temperature for s in normal_samples)
    assert hot_peak > normal_peak
    assert hot_peak > 100.0


def test_low_battery_scenario_lowers_voltage() -> None:
    low = SimulationEngine(make_settings(scenario="low_battery"))
    normal = SimulationEngine(make_settings(scenario="normal"))

    # Skip warm-up and OFF phases: after 100s the alternator is charging in
    # both runs, so every low-battery voltage must sit below the normal floor.
    low_samples = [s for s in run_states(low, 500)[100:] if s.state != DrivingState.OFF]
    normal_samples = [s for s in run_states(normal, 500)[100:] if s.state != DrivingState.OFF]

    low_max = max(s.battery_voltage for s in low_samples)
    normal_min = min(s.battery_voltage for s in normal_samples)
    assert low_max < normal_min
