"""Deterministic synthetic episode generation (plan §4.1).

Reuses the *shipped* simulator physics (:class:`simulator.telemetry_generator.
SimulationEngine`) rather than re-implementing a data generator, so the
evaluation exercises the same signal characteristics the platform ingests. The
reference label is the scenario the harness selected, recorded independently of
any analyzer output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from app.intelligence.models import SUPPORTED_METRICS, TelemetryPoint
from evaluation.registry import (
    SCENARIO_EXPECTED_RULES,
    SCENARIO_FAMILY,
    EpisodeProvenance,
    ScenarioSpec,
)
from simulator.config import SimulatorSettings
from simulator.telemetry_generator import SimulationEngine

#: Namespace for deterministic UUID derivation (vehicle/run identity).
_NAMESPACE = UUID("e0a1f2b3-0000-4000-8000-000000000001")

#: Fixed synthetic epoch so a dataset is byte-reproducible across machines.
_BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)

#: Generation-relevant simulator fields, pinned explicitly so an ambient
#: ``SIMULATOR_*`` environment value can never perturb the dataset.
_PINNED_GENERATION_FIELDS: dict[str, float] = {
    "initial_odometer": 45231.7,
    "initial_fuel_level": 75.0,
    "initial_engine_runtime": 0.0,
    "off_seconds": 2.0,
    "starting_seconds": 3.0,
    "idle_seconds": 10.0,
    "accelerating_seconds": 15.0,
    "cruising_seconds": 30.0,
    "decelerating_seconds": 10.0,
    "cruise_speed": 60.0,
}


def deterministic_uuid(dataset_id: str, scenario: str, seed: int, kind: str) -> UUID:
    return uuid5(_NAMESPACE, f"{dataset_id}:{scenario}:{seed}:{kind}")


def build_simulator_settings(spec: ScenarioSpec, *, run_id: UUID | None = None) -> SimulatorSettings:
    """Construct a fully pinned, deterministic simulator configuration."""
    vehicle_id = deterministic_uuid("synthetic", spec.scenario, spec.seed, "vehicle")
    resolved_run = run_id or deterministic_uuid("synthetic", spec.scenario, spec.seed, "run")
    return SimulatorSettings(
        vehicle_id=vehicle_id,
        run_id=resolved_run,
        scenario=spec.scenario,
        seed=spec.seed,
        interval_seconds=spec.interval_seconds,
        **_PINNED_GENERATION_FIELDS,
    )


@dataclass(frozen=True)
class Episode:
    """A generated episode: samples plus its frozen provenance record."""

    provenance: EpisodeProvenance
    points: list[TelemetryPoint]

    @property
    def episode_id(self) -> str:
        return self.provenance.episode_id

    @property
    def scenario(self) -> str:
        return self.provenance.scenario


def generate_episode(dataset_id: str, spec: ScenarioSpec) -> Episode:
    """Generate one deterministic episode from the real simulator engine."""
    if spec.scenario not in SCENARIO_FAMILY:
        raise ValueError(f"unknown scenario {spec.scenario!r}")
    if spec.duration_seconds <= 0 or spec.interval_seconds <= 0:
        raise ValueError("duration_seconds and interval_seconds must be positive")

    run_id = deterministic_uuid(dataset_id, spec.scenario, spec.seed, "run")
    settings = build_simulator_settings(spec, run_id=run_id)
    engine = SimulationEngine(settings)

    steps = int(round(spec.duration_seconds / spec.interval_seconds))
    points: list[TelemetryPoint] = []
    for index in range(steps):
        sample = engine.step(spec.interval_seconds)
        timestamp = _BASE_TIME + timedelta(seconds=index * spec.interval_seconds)
        points.append(
            TelemetryPoint(
                timestamp=timestamp,
                values={metric: getattr(sample, metric, None) for metric in SUPPORTED_METRICS},
            )
        )

    expected_rules, min_severity = SCENARIO_EXPECTED_RULES[spec.scenario]
    provenance = EpisodeProvenance(
        dataset_id=dataset_id,
        episode_id=f"{spec.scenario}-seed{spec.seed}",
        scenario=spec.scenario,
        seed=spec.seed,
        run_id=str(run_id),
        duration_seconds=spec.duration_seconds,
        interval_seconds=spec.interval_seconds,
        reference_family=SCENARIO_FAMILY[spec.scenario],
        expected_rule_ids=expected_rules,
        expected_min_severity=min_severity,
    )
    return Episode(provenance=provenance, points=points)


def steady_suffix(points: list[TelemetryPoint], spec: ScenarioSpec) -> list[TelemetryPoint]:
    """The primary-view subset: the last ``steady_suffix_seconds`` of the episode."""
    if not points:
        return []
    last_ts = points[-1].timestamp
    cutoff = last_ts - timedelta(seconds=spec.steady_suffix_seconds)
    return [point for point in points if point.timestamp > cutoff]


def build_dataset_specs(
    scenarios: tuple[str, ...], seeds: tuple[int, ...], *, duration_seconds: float = 180.0
) -> list[ScenarioSpec]:
    return [
        ScenarioSpec(scenario=scenario, seed=seed, duration_seconds=duration_seconds)
        for scenario in scenarios
        for seed in seeds
    ]
