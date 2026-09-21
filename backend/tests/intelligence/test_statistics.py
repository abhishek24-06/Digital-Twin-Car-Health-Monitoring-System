from __future__ import annotations

import math
from datetime import UTC, datetime

from app.intelligence.models import TelemetryPoint
from app.intelligence.statistics import analyze_metric, analyze_metrics


def test_analyze_metric_empty_returns_none() -> None:
    stats = analyze_metric("speed", [])
    assert stats is None


def test_analyze_metric_all_invalid_returns_none() -> None:
    stats = analyze_metric("speed", [None, float("nan"), float("inf")])
    assert stats is None


def test_analyze_metric_ignores_none_and_non_finite() -> None:
    stats = analyze_metric("rpm", [1000.0, 2000.0, None, float("nan"), 3000.0, float("inf")])
    assert stats is not None
    assert stats.count == 3
    assert stats.unit == "RPM"
    assert stats.mean == 2000.0
    assert stats.minimum == 1000.0
    assert stats.maximum == 3000.0
    assert stats.first == 1000.0
    assert stats.last == 3000.0


def test_analyze_metric_single_sample_limits_support_stats() -> None:
    stats = analyze_metric("battery_voltage", [12.5])
    assert stats is not None
    assert stats.count == 1
    assert stats.std_dev is None
    assert stats.coefficient_of_variation is None
    assert stats.median == 12.5
    assert stats.percentile_25 == 12.5
    assert stats.percentile_75 == 12.5
    assert stats.range == 0.0


def test_analyze_metric_constant_series_zero_spread() -> None:
    stats = analyze_metric("fuel_level", [60.0, 60.0, 60.0, 60.0])
    assert stats is not None
    assert stats.std_dev == 0.0
    assert stats.mean == 60.0
    assert stats.minimum == stats.maximum == stats.median == 60.0
    assert stats.coefficient_of_variation == 0.0


def test_analyze_metric_median_is_robust_to_outliers() -> None:
    stats = analyze_metric("engine_load", [10.0, 12.0, 11.0, 13.0, 90.0])
    assert stats is not None
    assert stats.median == 12.0
    assert stats.percentile_25 == 11.0
    assert stats.percentile_75 == 13.0


def test_analyze_metric_sample_std_dev_uses_n_minus_1() -> None:
    stats = analyze_metric("speed", [10.0, 12.0, 14.0])
    assert stats is not None
    assert stats.mean == 12.0
    assert math.isclose(stats.std_dev or 0.0, 2.0, rel_tol=1e-9)


def test_analyze_metric_unknown_unit_defaults_to_empty() -> None:
    stats = analyze_metric("no_such_metric", [1.0, 2.0])
    assert stats is not None
    assert stats.unit == ""


def test_analyze_metric_never_emits_nan_or_inf() -> None:
    stats = analyze_metric("speed", [1.0, 2.0, 3.0, 4.0])
    assert stats is not None
    payload = stats.model_dump()
    for value in payload.values():
        assert not isinstance(value, float) or math.isfinite(value)


def test_analyze_metrics_only_includes_present_metrics() -> None:
    points = [
        _point({"speed": 10.0, "rpm": 1000.0, "fuel_level": None}),
        _point({"speed": 20.0, "rpm": 2000.0, "fuel_level": None}),
    ]
    statistics = analyze_metrics(points, ("speed", "rpm", "fuel_level"))

    assert set(statistics) == {"speed", "rpm"}


def test_analyze_metrics_skips_empty_series() -> None:
    statistics = analyze_metrics([_point({})], ("speed",))
    assert statistics == {}


def _point(values: dict) -> TelemetryPoint:
    return TelemetryPoint(timestamp=datetime.now(UTC), values=values)
