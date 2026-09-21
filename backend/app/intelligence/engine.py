"""Deterministic vehicle health analysis orchestration.

The engine is transport-agnostic: it consumes typed ``TelemetryPoint`` samples
(plus optional historical points for the baseline) and produces a complete
``HealthContext``. It never touches the database, MQTT or the API, so it works
identically for telemetry ingested via MQTT, REST, replay systems, tests or
historical data.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import UTC, datetime
from uuid import UUID

from app.intelligence.baselines import analyze_baselines
from app.intelligence.context import build_context
from app.intelligence.models import (
    SUPPORTED_METRICS,
    AnalysisWindow,
    DataQuality,
    Finding,
    HealthContext,
    TelemetryPoint,
)
from app.intelligence.rules import INSUFFICIENT_DATA_RULE, HealthRuleEngine
from app.intelligence.scoring import compute_confidence, insufficient_score, score_findings
from app.intelligence.statistics import analyze_metrics
from app.intelligence.trends import analyze_trends

logger = logging.getLogger(__name__)


def compute_data_quality(
    samples: list[TelemetryPoint],
    window: AnalysisWindow,
    expected_interval_seconds: float,
) -> DataQuality:
    """Compute data-quality metrics for the analysis window."""
    sample_count = len(samples)
    window_seconds = window.duration_seconds
    interval = max(expected_interval_seconds, 1e-9)
    expected_sample_count = math.ceil(window_seconds / interval) if window_seconds > 0 else 0
    coverage = (
        round(min(1.0, sample_count / expected_sample_count), 4)
        if expected_sample_count > 0
        else (1.0 if sample_count > 0 else 0.0)
    )

    first_ts = samples[0].timestamp if samples else None
    last_ts = samples[-1].timestamp if samples else None
    duration_seconds = (
        round((last_ts - first_ts).total_seconds(), 3) if first_ts and last_ts else None
    )
    max_gap = None
    if len(samples) >= 2:
        max_gap = round(
            max(
                (samples[i + 1].timestamp - samples[i].timestamp).total_seconds()
                for i in range(len(samples) - 1)
            ),
            3,
        )
    missing = max(0, expected_sample_count - sample_count) if expected_sample_count else 0
    order_valid = all(
        samples[i].timestamp <= samples[i + 1].timestamp for i in range(len(samples) - 1)
    )

    return DataQuality(
        sample_count=sample_count,
        expected_sample_count=expected_sample_count,
        coverage_ratio=coverage,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        duration_seconds=duration_seconds,
        missing_sample_estimate=missing,
        max_gap_seconds=max_gap,
        timestamp_order_valid=order_valid,
    )


class HealthAnalysisEngine:
    """Orchestrates statistics → trends → baselines → rules → scoring → context."""

    def __init__(self, rule_engine: HealthRuleEngine | None = None) -> None:
        self._rule_engine = rule_engine or HealthRuleEngine()

    def analyze(
        self,
        *,
        vehicle_id: UUID,
        window: AnalysisWindow,
        samples: list[TelemetryPoint],
        history: list[TelemetryPoint] | None = None,
        minimum_samples: int = 10,
        expected_interval_seconds: float = 1.0,
        baseline_minimum_samples: int = 5,
        generated_at: datetime | None = None,
    ) -> HealthContext:
        started = time.perf_counter()
        generated_at = generated_at or datetime.now(UTC)
        history = history or []
        baseline_minimum = baseline_minimum_samples

        data_quality = compute_data_quality(samples, window, expected_interval_seconds)
        statistics = analyze_metrics(samples, SUPPORTED_METRICS)
        trends = analyze_trends(samples, SUPPORTED_METRICS)

        insufficient = data_quality.sample_count < minimum_samples
        if insufficient:
            findings = [
                Finding(
                    rule_id=INSUFFICIENT_DATA_RULE,
                    severity="info",
                    category="data_quality",
                    metric=None,
                    message="Insufficient telemetry data for a reliable health assessment.",
                    confidence=0.5,
                    window_start=window.start,
                    window_end=window.end,
                )
            ]
            score_details = insufficient_score(
                notes=[
                    f"sample_count ({data_quality.sample_count}) is below minimum_samples ({minimum_samples})"
                ]
            )
            confidence = compute_confidence(data_quality, statistics, window)
        else:
            findings = self._rule_engine.evaluate(
                statistics=statistics,
                data_quality=data_quality,
                window=window,
                expected_interval_seconds=expected_interval_seconds,
            )
            score_details = score_findings(findings)
            confidence = compute_confidence(data_quality, statistics, window)

        baselines = []
        if history and not insufficient and len(history) >= baseline_minimum:
            baselines = analyze_baselines(history, samples, SUPPORTED_METRICS)

        duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
        context = build_context(
            vehicle_id=vehicle_id,
            generated_at=generated_at,
            analysis_duration_ms=duration_ms,
            analysis_window=window,
            data_quality=data_quality,
            statistics=statistics,
            trends=trends,
            baselines=baselines,
            findings=findings,
            score_details=score_details,
            confidence=confidence,
        )
        logger.info(
            "health analysis: vehicle_id=%s samples=%s score=%s status=%s findings=%s "
            "coverage=%s duration_ms=%s",
            vehicle_id,
            data_quality.sample_count,
            score_details.score,
            score_details.status,
            len(findings),
            data_quality.coverage_ratio,
            duration_ms,
        )
        return context
