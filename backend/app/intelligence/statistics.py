"""Deterministic statistical analysis engine.

Calculates robust summary statistics for numeric telemetry metrics. Safe for
empty input, single-sample input, constant series, missing/null values and
non-finite values (which are treated as missing).

Never emits NaN or Infinity: metrics that cannot be meaningfully computed are
reported as ``None``.
"""

from __future__ import annotations

import math

from app.intelligence.models import METRIC_UNITS, MetricStatistics

#: Default rounding applied to computed statistical values.
_DECIMALS = 6


def _round(value: float) -> float:
    return round(value, _DECIMALS)


def _median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    midpoint = n // 2
    if n % 2 == 1:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2.0


def _sample_std_dev(values: list[float]) -> float | None:
    """Sample standard deviation (n-1 denominator); None if fewer than 2 samples."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def _percentile(sorted_values: list[float], percentile: float) -> float:
    """Linear-interpolated percentile (numpy-compatible default method)."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    position = percentile * (n - 1)
    lower = int(position)
    fraction = position - lower
    if lower >= n - 1:
        return sorted_values[n - 1]
    return sorted_values[lower] + fraction * (sorted_values[lower + 1] - sorted_values[lower])


def analyze_metric(metric: str, values: list[float | None]) -> MetricStatistics | None:
    """Compute statistics for a single metric from raw ``values``.

    Non-finite or ``None`` values are ignored. Returns ``None`` when no valid
    value exists (the caller should omit the metric entirely).
    """
    unit = METRIC_UNITS.get(metric, "")
    valid = [v for v in values if v is not None and math.isfinite(v)]
    count = len(valid)
    if count == 0:
        return None

    sorted_values = sorted(valid)
    minimum = sorted_values[0]
    maximum = sorted_values[-1]
    mean = sum(valid) / count
    median = _median(sorted_values)
    std_dev = _sample_std_dev(valid)
    first = valid[0]
    last = valid[-1]
    value_range = maximum - minimum
    p25 = _percentile(sorted_values, 0.25)
    p75 = _percentile(sorted_values, 0.75)
    cv = std_dev / abs(mean) if std_dev is not None and abs(mean) > 1e-12 else None

    return MetricStatistics(
        metric=metric,
        unit=unit,
        count=count,
        minimum=_round(minimum),
        maximum=_round(maximum),
        mean=_round(mean),
        median=_round(median),
        std_dev=_round(std_dev) if std_dev is not None else None,
        first=_round(first),
        last=_round(last),
        range=_round(value_range),
        percentile_25=_round(p25),
        percentile_75=_round(p75),
        coefficient_of_variation=_round(cv) if cv is not None else None,
    )


def analyze_metrics(points: list, metrics: tuple[str, ...]) -> dict[str, MetricStatistics]:
    """Compute statistics for every supported metric across all samples.

    ``points`` are objects with a ``values`` mapping (see ``TelemetryPoint``).
    """
    statistics: dict[str, MetricStatistics] = {}
    for metric in metrics:
        values = [point.values.get(metric) for point in points]
        stats = analyze_metric(metric, values)
        if stats is not None:
            statistics[metric] = stats
    return statistics
