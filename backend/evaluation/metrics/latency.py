"""Latency metrics (plan §6, RQ4).

Only *software pipeline* latency is defined here. The full
publish-to-alert-persisted latency requires the isolated MQTT + DB harness (the
Phase C pattern) and is not measured by the pure analyzer pass; this module
covers deterministic compute latency (``analysis_duration_ms``).

Percentile justification
------------------------
A nearest-rank percentile is only a defensible estimate when the sample count is
large enough that the chosen rank is an interior order statistic rather than the
sample maximum. Following the rule of thumb ``n >= 1 / (1 - p)``:

* ``p95`` requires ``n >= 20`` samples;
* ``p99`` requires ``n >= 100`` samples.

When the count is smaller the percentile is reported as ``None`` with a
``*_justified`` flag of ``False`` so a report can say "not justified" instead of
presenting the maximum as if it were a 99th percentile. This is a reporting
correctness rule; it never changes the underlying samples.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Minimum sample counts for which each percentile is a defensible estimate.
MIN_SAMPLES_FOR_P95 = 20
MIN_SAMPLES_FOR_P99 = 100


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile (no interpolation), robust for small n."""
    if not values:
        return None
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be in [0, 1]")
    ordered = sorted(values)
    if fraction == 0.0:
        return ordered[0]
    index = max(0, min(len(ordered) - 1, int(round(fraction * len(ordered))) - 1))
    return ordered[index]


def summarize_latency(samples: Sequence[float | None]) -> dict[str, float | int | bool | None]:
    """min/p50/p95/p99/max/mean for one latency series, with percentile gates.

    All numeric fields are rounded to 3 decimal places so the JSON artifact and
    the Markdown report always render the same value. ``p95``/``p99`` are
    ``None`` when the sample count cannot justify them (see module docstring).
    """
    values = [float(s) for s in samples if s is not None]
    if not values:
        return {
            "count": 0,
            "min": None,
            "p50": None,
            "p95": None,
            "p95_justified": False,
            "p99": None,
            "p99_justified": False,
            "max": None,
            "mean": None,
        }
    count = len(values)
    p95_justified = count >= MIN_SAMPLES_FOR_P95
    p99_justified = count >= MIN_SAMPLES_FOR_P99
    return {
        "count": count,
        "min": round(min(values), 3),
        "p50": _round(percentile(values, 0.50)),
        "p95": _round(percentile(values, 0.95)) if p95_justified else None,
        "p95_justified": p95_justified,
        "p99": _round(percentile(values, 0.99)) if p99_justified else None,
        "p99_justified": p99_justified,
        "max": round(max(values), 3),
        "mean": round(sum(values) / count, 3),
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


__all__ = [
    "MIN_SAMPLES_FOR_P95",
    "MIN_SAMPLES_FOR_P99",
    "percentile",
    "summarize_latency",
]
