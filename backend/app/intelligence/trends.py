"""Deterministic trend analysis.

Method (documented): for each metric, ordinary least-squares linear regression
of value against elapsed seconds over the analysis window. The slope
(units/second) quantifies direction; the ``normalized_slope`` expresses the
relative change across the whole window (``slope * span / |mean|``), making
trends comparable across metrics with different units and scales.

Direction is derived from the sign of the slope with a small hysteresis band;
strength thresholds are applied to the absolute normalized slope and are
centralized here.
"""

from __future__ import annotations

from app.intelligence.models import METRIC_UNITS, TelemetryPoint, TrendInsight

#: Fewer valid samples than this → insufficient data for a trend verdict.
TREND_MIN_SAMPLES = 3

#: Trend direction classification (normalized slope, absolute value).
STABLE_EPSILON = 0.01

#: Trend strength thresholds on absolute normalized slope (upper bounds).
STRENGTH_THRESHOLDS: dict[str, float] = {
    "none": 0.01,
    "weak": 0.08,
    "moderate": 0.25,
}


def _classify_strength(normalized: float) -> str:
    magnitude = abs(normalized)
    if magnitude < STRENGTH_THRESHOLDS["none"]:
        return "none"
    if magnitude < STRENGTH_THRESHOLDS["weak"]:
        return "weak"
    if magnitude < STRENGTH_THRESHOLDS["moderate"]:
        return "moderate"
    return "strong"


def analyze_trend(metric: str, points: list[TelemetryPoint]) -> TrendInsight:
    """Detect the direction of change for ``metric`` across ``points``."""
    unit = METRIC_UNITS.get(metric, "")

    valid = [
        (point.timestamp, value)
        for point in points
        if (value := point.values.get(metric)) is not None
    ]
    count = len(valid)
    if count < TREND_MIN_SAMPLES:
        return TrendInsight(
            metric=metric,
            unit=unit,
            direction="insufficient_data",
            slope=None,
            normalized_slope=None,
            strength=None,
            sample_count=count,
        )

    origin = valid[0][0].timestamp()
    xs = [float(valid[i][0].timestamp() - origin) for i in range(count)]
    ys = [valid[i][1] for i in range(count)]

    n = float(count)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
        if denominator > 1e-12
        else 0.0
    )

    span = xs[-1] - xs[0]
    normalized = None
    if span > 1e-12 and abs(mean_y) > 1e-12:
        normalized = slope * span / abs(mean_y)

    direction = "stable"
    if normalized is not None:
        if normalized > STABLE_EPSILON:
            direction = "increasing"
        elif normalized < -STABLE_EPSILON:
            direction = "decreasing"
    strength = _classify_strength(normalized) if normalized is not None else None

    return TrendInsight(
        metric=metric,
        unit=unit,
        direction=direction,
        slope=round(slope, 8),
        normalized_slope=round(normalized, 6) if normalized is not None else None,
        strength=strength,
        sample_count=count,
    )


def analyze_trends(points: list[TelemetryPoint], metrics: tuple[str, ...]) -> list[TrendInsight]:
    """Detect trends for every supported metric across ``points``."""
    return [analyze_trend(metric, points) for metric in metrics]
