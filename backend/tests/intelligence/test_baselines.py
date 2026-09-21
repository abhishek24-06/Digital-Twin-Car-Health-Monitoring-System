from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.intelligence.baselines import analyze_baseline, analyze_baselines
from app.intelligence.models import TelemetryPoint


def _point(values: dict) -> TelemetryPoint:
    return TelemetryPoint(timestamp=datetime.now(UTC), values=values)


def _history(values: list[float]) -> list[TelemetryPoint]:
    return [_point({"coolant_temperature": v}) for v in values]


def _window(values: list[float]) -> list[TelemetryPoint]:
    return [_point({"coolant_temperature": v}) for v in values]


def test_baseline_insufficient_history_below_minimum() -> None:
    insight = analyze_baseline("coolant_temperature", [90.0, 91.0], 92.0)
    assert insight.status == "insufficient_history"
    assert insight.center is None
    assert insight.spread is None
    assert insight.normalized_deviation is None


def test_baseline_current_none_is_insufficient() -> None:
    insight = analyze_baseline("coolant_temperature", [90.0] * 6, None)
    assert insight.status == "insufficient_history"


def test_baseline_within_band() -> None:
    history = [88.0, 90.0, 92.0, 91.0, 89.0, 90.5, 91.5]
    insight = analyze_baseline("coolant_temperature", history, 91.0)
    assert insight.status == "within"
    assert insight.spread is not None and insight.spread > 0
    assert abs(insight.normalized_deviation or 0.0) <= 2.0


def test_baseline_elevated_when_current_is_far_above() -> None:
    history = [88.0, 90.0, 92.0, 87.0, 93.0, 91.0, 89.0]
    insight = analyze_baseline("coolant_temperature", history, 120.0)
    assert insight.status == "elevated"
    assert insight.normalized_deviation is not None and insight.normalized_deviation > 2.0


def test_baseline_depressed_when_current_is_far_below() -> None:
    history = [88.0, 90.0, 92.0, 87.0, 93.0, 91.0, 89.0]
    insight = analyze_baseline("coolant_temperature", history, 70.0)
    assert insight.status == "depressed"
    assert insight.normalized_deviation is not None and insight.normalized_deviation < -2.0


def test_baseline_constant_history_no_spread() -> None:
    insight = analyze_baseline("coolant_temperature", [90.0] * 6, 90.0)
    assert insight.status == "within"
    assert insight.spread == 0.0
    assert insight.normalized_deviation is None
    assert insight.note is not None


def test_baseline_constant_history_elevated_when_above_center() -> None:
    insight = analyze_baseline("coolant_temperature", [90.0] * 6, 102.0)
    assert insight.status == "elevated"
    assert insight.normalized_deviation is None


def test_analyze_baselines_uses_last_window_value_as_current() -> None:
    history = [_point({"speed": v, "engine_load": v}) for v in [50.0, 55.0, 52.0, 53.0, 51.0, 54.0]]
    window = [_point({"speed": 80.0, "engine_load": 40.0})]
    insights = analyze_baselines(history, window, ("speed", "engine_load"))

    by_metric = {i.metric: i for i in insights}
    assert by_metric["speed"].status == "elevated"
    assert by_metric["speed"].current_value == 80.0
    assert by_metric["engine_load"].current_value == 40.0


def test_analyze_baselines_handles_missing_current() -> None:
    history = [_point({"speed": 50.0}) for _ in range(6)]
    window = [_point({})]
    insights = analyze_baselines(history, window, ("speed", "fuel_level"))
    by_metric = {i.metric: i for i in insights}
    assert by_metric["speed"].status == "insufficient_history"
    assert by_metric["fuel_level"].status == "insufficient_history"


def test_timestamps_do_not_affect_baseline() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    history = [
        TelemetryPoint(timestamp=base, values={"coolant_temperature": 90.0}),
        TelemetryPoint(timestamp=base + timedelta(seconds=5), values={"coolant_temperature": 92.0}),
    ]
    # Fewer than BASELINE_MIN_SAMPLES -> insufficient regardless of timestamps.
    insight = analyze_baseline(
        "coolant_temperature", [p.values.get("coolant_temperature") for p in history], 100.0
    )
    assert insight.status == "insufficient_history"
