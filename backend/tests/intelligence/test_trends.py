from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.intelligence.models import TelemetryPoint
from app.intelligence.trends import analyze_trend, analyze_trends


def _points(values: list[float], start_seconds_ago: float = 500) -> list[TelemetryPoint]:
    start = datetime.now(UTC) - timedelta(seconds=start_seconds_ago)
    return [
        TelemetryPoint(
            timestamp=start + timedelta(seconds=index),
            values={"coolant_temperature": value},
        )
        for index, value in enumerate(values)
    ]


def test_trend_insufficient_data_below_minimum_samples() -> None:
    insight = analyze_trend("coolant_temperature", _points([90.0, 91.0]))
    assert insight.direction == "insufficient_data"
    assert insight.slope is None
    assert insight.normalized_slope is None
    assert insight.strength is None
    assert insight.sample_count == 2


def test_trend_strong_increasing() -> None:
    values = [float(40 + i) for i in range(40)]  # 40 -> 79 over 39s
    insight = analyze_trend("coolant_temperature", _points(values))
    assert insight.direction == "increasing"
    assert insight.strength == "strong"
    assert insight.slope is not None and insight.slope > 0
    assert insight.normalized_slope is not None and insight.normalized_slope > 0
    assert insight.sample_count == 40
    assert insight.unit == "C"


def test_trend_strong_decreasing() -> None:
    values = [float(79 - i) for i in range(40)]
    insight = analyze_trend("coolant_temperature", _points(values))
    assert insight.direction == "decreasing"
    assert insight.strength == "strong"
    assert insight.slope is not None and insight.slope < 0
    assert insight.normalized_slope is not None and insight.normalized_slope < 0


def test_trend_stable_constant_series() -> None:
    insight = analyze_trend("coolant_temperature", _points([90.0] * 20))
    assert insight.direction == "stable"
    assert insight.strength == "none"
    assert insight.normalized_slope is not None
    assert abs(insight.normalized_slope) <= 0.01


def test_trend_ignores_none_values_before_detection() -> None:
    values = [90.0, None, None, 120.0, None, 150.0]
    insight = analyze_trend("coolant_temperature", _points(values))
    assert insight.sample_count == 3
    assert insight.direction == "increasing"


def test_trend_weak_when_normalized_slope_is_small() -> None:
    values = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]  # small relative change
    insight = analyze_trend("coolant_temperature", _points(values))
    assert insight.direction == "increasing"
    assert insight.strength == "weak"


def test_analyze_trends_covers_every_metric() -> None:
    points = _points([float(i) for i in range(20)])
    insights = analyze_trends(points, ("coolant_temperature", "speed"))
    assert {i.metric for i in insights} == {"coolant_temperature", "speed"}
