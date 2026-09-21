from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.intelligence.engine import HealthAnalysisEngine
from app.intelligence.models import AnalysisWindow, TelemetryPoint

VEHICLE_ID = uuid4()


def _window(minutes: float = 1.0) -> AnalysisWindow:
    end = datetime.now(UTC)
    return AnalysisWindow(start=end - timedelta(minutes=minutes), end=end, window_minutes=minutes)


def _points(
    base_values: dict, *, count: int = 60, start_seconds_ago: float = 60.0, step: float = 1.0
) -> list[TelemetryPoint]:
    start = datetime.now(UTC) - timedelta(seconds=start_seconds_ago)
    points: list[TelemetryPoint] = []
    for index in range(count):
        points.append(
            TelemetryPoint(
                timestamp=start + timedelta(seconds=index * step),
                values={k: (v + index if k == "rpm" else v) for k, v in base_values.items()},
            )
        )
    return points


def _healthy_base() -> dict:
    return {
        "rpm": 2500.0,
        "speed": 60.0,
        "engine_load": 30.0,
        "coolant_temperature": 90.0,
        "oil_temperature": 90.0,
        "battery_voltage": 13.5,
        "fuel_level": 60.0,
        "intake_air_temperature": 25.0,
        "throttle_position": 20.0,
        "engine_runtime": 1000.0,
        "odometer": 50000.0,
    }


def test_engine_healthy_window_produces_healthy_context() -> None:
    window = _window()
    samples = _points(_healthy_base(), count=61, start_seconds_ago=60.0)
    context = HealthAnalysisEngine().analyze(
        vehicle_id=VEHICLE_ID,
        window=window,
        samples=samples,
        minimum_samples=10,
        expected_interval_seconds=1.0,
    )

    assert context.health_status == "healthy"
    assert context.health_score == 100.0
    assert context.confidence == 1.0
    assert context.findings == []
    assert context.data_quality.sample_count == 61
    assert context.data_quality.coverage_ratio == 1.0
    assert context.context_schema_version == "1.0"
    assert context.rule_engine_version == "1.0"
    assert len(context.statistics) == 11
    assert context.score_details.starting_score == 100.0


def test_engine_insufficient_samples_yields_unknown_status() -> None:
    window = _window()
    samples = _points(_healthy_base(), count=4, start_seconds_ago=4.0)
    context = HealthAnalysisEngine().analyze(
        vehicle_id=VEHICLE_ID,
        window=window,
        samples=samples,
        minimum_samples=10,
        expected_interval_seconds=1.0,
    )

    assert context.health_status == "unknown"
    assert context.health_score is None
    assert [f.rule_id for f in context.findings] == ["INSUFFICIENT_DATA"]
    assert context.score_details.notes
    assert context.data_quality.sample_count == 4


def test_engine_high_temperature_triggers_critical_finding() -> None:
    base = _healthy_base()
    base["coolant_temperature"] = 115.0
    samples = _points(base, count=61, start_seconds_ago=60.0)
    context = HealthAnalysisEngine().analyze(
        vehicle_id=VEHICLE_ID,
        window=_window(),
        samples=samples,
        minimum_samples=10,
        expected_interval_seconds=1.0,
    )

    assert context.health_status == "attention"
    assert context.health_score == 70.0
    severities = {f.rule_id: f.severity for f in context.findings}
    assert severities["COOLANT_TEMP_HIGH"] == "critical"
    assert context.score_details.components[0].category == "temperature"


def test_engine_uses_history_for_baselines() -> None:
    base = _healthy_base()
    history = _points(base, count=30, start_seconds_ago=400.0, step=5.0)

    hot = dict(base)
    hot["coolant_temperature"] = 118.0
    samples = _points(hot, count=61, start_seconds_ago=60.0)

    context = HealthAnalysisEngine().analyze(
        vehicle_id=VEHICLE_ID,
        window=_window(),
        samples=samples,
        history=history,
        minimum_samples=10,
        expected_interval_seconds=1.0,
        baseline_minimum_samples=5,
    )

    baseline_by_metric = {b.metric: b for b in context.baselines}
    assert context.baselines
    assert baseline_by_metric["coolant_temperature"].status == "elevated"


def test_engine_baselines_skipped_without_history() -> None:
    samples = _points(_healthy_base(), count=61, start_seconds_ago=60.0)
    context = HealthAnalysisEngine().analyze(
        vehicle_id=VEHICLE_ID,
        window=_window(),
        samples=samples,
        history=[],
        minimum_samples=10,
        expected_interval_seconds=1.0,
    )
    assert context.baselines == []


def test_engine_gap_in_telemetry_is_reported() -> None:
    base = _healthy_base()
    first_block = _points(base, count=30, start_seconds_ago=59.0, step=1.0)
    second_block = _points(base, count=10, start_seconds_ago=9.0, step=1.0)
    samples = sorted([*first_block, *second_block], key=lambda p: p.timestamp)
    gaps = [
        (b.timestamp - a.timestamp).total_seconds()
        for a, b in zip(samples, samples[1:], strict=False)
    ]
    assert max(gaps) > 3.0  # ~20s gap between the blocks

    context = HealthAnalysisEngine().analyze(
        vehicle_id=VEHICLE_ID,
        window=_window(),
        samples=samples,
        minimum_samples=10,
        expected_interval_seconds=1.0,
    )

    rule_ids = {f.rule_id for f in context.findings}
    assert "TELEMETRY_GAP" in rule_ids


def test_engine_generated_at_is_controllable() -> None:
    fixed = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    samples = _points(_healthy_base(), count=61, start_seconds_ago=60.0)
    context = HealthAnalysisEngine().analyze(
        vehicle_id=VEHICLE_ID,
        window=_window(),
        samples=samples,
        minimum_samples=10,
        expected_interval_seconds=1.0,
        generated_at=fixed,
    )
    assert context.generated_at == fixed


def test_engine_context_serialisable_to_json() -> None:
    import json

    samples = _points(_healthy_base(), count=61, start_seconds_ago=60.0)
    context = HealthAnalysisEngine().analyze(
        vehicle_id=VEHICLE_ID,
        window=_window(),
        samples=samples,
        minimum_samples=10,
        expected_interval_seconds=1.0,
    )
    payload = context.model_dump(mode="json")
    assert isinstance(payload["vehicle_id"], str)
    json.dumps(payload)
    assert payload["health_status"] == "healthy"
