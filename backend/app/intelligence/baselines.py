"""Vehicle-specific historical baseline comparison.

Method (documented): the baseline for each metric is the vehicle's own recent
history, summarized by the median (robust center) and the scaled median
absolute deviation (robust spread): ``spread = 1.4826 * MAD``.

The current value (the last value observed in the analysis window) is compared
to ``center +/- spread``. A normalized deviation ``(current - center) / spread``
larger than ``DEVIATION_THRESHOLD`` (or smaller than its negative) marks the
metric as elevated (or depressed) relative to this vehicle's own behavior.

No manufacturer specification is used; when the vehicle has no usable history
the baseline reports ``insufficient_history``.
"""

from __future__ import annotations

import math

from app.intelligence.models import (
    METRIC_UNITS,
    BaselineInsight,
    TelemetryPoint,
)

#: Fewer usable history samples than this → insufficient baseline history.
BASELINE_MIN_SAMPLES = 5

#: MAD scaling constant so spread approximates the standard deviation for
#: normally distributed data.
MAD_SCALE = 1.4826

#: Normalized-deviation threshold for "elevated"/"depressed".
DEVIATION_THRESHOLD = 2.0


def _median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    midpoint = n // 2
    if n % 2 == 1:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2.0


def _scaled_mad(center: float, values: list[float]) -> float:
    deviations = [abs(value - center) for value in values]
    return MAD_SCALE * _median(sorted(deviations))


def analyze_baseline(
    metric: str, history_values: list[float | None], current_value: float | None
) -> BaselineInsight:
    """Compare ``current_value`` against historical values for a metric."""
    unit = METRIC_UNITS.get(metric, "")
    valid = [v for v in history_values if v is not None and math.isfinite(v)]
    count = len(valid)

    if count < BASELINE_MIN_SAMPLES or current_value is None:
        return BaselineInsight(
            metric=metric,
            unit=unit,
            center=None,
            spread=None,
            sample_count=count,
            current_value=current_value,
            normalized_deviation=None,
            status="insufficient_history",
            note="Insufficient historical telemetry for a baseline comparison.",
        )

    center = _median(sorted(valid))
    spread = max(_scaled_mad(center, valid), 0.0)
    deviation = None
    status = "within"
    note = None

    if spread > 1e-12:
        deviation = round((current_value - center) / spread, 4)
        if deviation > DEVIATION_THRESHOLD:
            status = "elevated"
        elif deviation < -DEVIATION_THRESHOLD:
            status = "depressed"
        else:
            status = "within"
    else:
        note = "Historical baseline has no measurable spread."
        if current_value > center:
            status = "elevated"
        elif current_value < center:
            status = "depressed"
        else:
            status = "within"

    return BaselineInsight(
        metric=metric,
        unit=unit,
        center=round(center, 6),
        spread=round(spread, 6),
        sample_count=count,
        current_value=round(current_value, 6),
        normalized_deviation=deviation,
        status=status,
        note=note,
    )


def analyze_baselines(
    history_points: list[TelemetryPoint],
    window_points: list[TelemetryPoint],
    metrics: tuple[str, ...],
) -> list[BaselineInsight]:
    """Build baselines for every metric using window last values as current."""
    latest: dict[str, float | None] = {}
    for metric in metrics:
        value = None
        for point in window_points:  # already chronological → keep last
            candidate = point.values.get(metric)
            if candidate is not None:
                value = candidate
        latest[metric] = value

    baselines: list[BaselineInsight] = []
    for metric in metrics:
        history = [point.values.get(metric) for point in history_points]
        baselines.append(analyze_baseline(metric, history, latest.get(metric)))
    return baselines
