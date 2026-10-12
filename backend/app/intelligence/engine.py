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
    LiveSufficiencyPolicy,
    LiveSufficiencyState,
    TelemetryPoint,
)
from app.intelligence.rules import (
    INSUFFICIENT_DATA_RULE,
    LIMITED_DATA_RULE,
    LIVE_SUFFICIENCY_RULE,
    HealthRuleEngine,
)
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


def evaluate_live_sufficiency(
    data_quality: DataQuality,
    policy: LiveSufficiencyPolicy,
    now: datetime,
) -> LiveSufficiencyState:
    """Evaluate a current-session's evidence against the live sufficiency gate.

    Every bound is per active run: samples, observation duration, coverage of
    the run's observation window, and freshness of the newest sample. Historical
    or unknown-run samples never contribute.
    """
    reasons: list[str] = []
    sample_count = data_quality.sample_count
    if sample_count < policy.minimum_samples:
        reasons.append(
            f"only {sample_count} current-run sample(s); at least "
            f"{policy.minimum_samples} required"
        )

    duration = data_quality.duration_seconds
    if duration is None:
        reasons.append("no current-run telemetry observed yet")
    elif duration < policy.minimum_duration_seconds:
        reasons.append(
            f"observation spans {duration:.0f}s; at least "
            f"{policy.minimum_duration_seconds:.0f}s required"
        )

    coverage = data_quality.coverage_ratio
    if coverage is None:
        coverage = 0.0
    if coverage < policy.minimum_coverage:
        reasons.append(
            f"coverage is {coverage:.0%}; at least {policy.minimum_coverage:.0%} required"
        )

    age: float | None = None
    if data_quality.last_timestamp is not None:
        age = max(0.0, (now - data_quality.last_timestamp).total_seconds())
    if age is None:
        reasons.append("newest current-run sample is unknown (stale feed)")
    elif age > policy.max_sample_age_seconds:
        reasons.append(
            f"newest current-run sample is {age:.0f}s old; at most "
            f"{policy.max_sample_age_seconds:.0f}s required"
        )

    return LiveSufficiencyState(
        policy_met=not reasons,
        sample_count=sample_count,
        required_sample_count=policy.minimum_samples,
        observation_duration_seconds=duration,
        required_duration_seconds=policy.minimum_duration_seconds,
        coverage_ratio=coverage,
        required_coverage=policy.minimum_coverage,
        latest_sample_age_seconds=age,
        max_sample_age_seconds=policy.max_sample_age_seconds,
        reasons=reasons,
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
        simulation_run_id: UUID | None = None,
        sufficiency_policy: LiveSufficiencyPolicy | None = None,
    ) -> HealthContext:
        started = time.perf_counter()
        generated_at = generated_at or datetime.now(UTC)
        history = history or []
        baseline_minimum = baseline_minimum_samples

        data_quality = compute_data_quality(samples, window, expected_interval_seconds)
        statistics = analyze_metrics(samples, SUPPORTED_METRICS)
        trends = analyze_trends(samples, SUPPORTED_METRICS)

        # Live current-session gate: unless the active run clears every bound,
        # the assessment stays provisional even when the old 10-sample cutover
        # would have called it definitive.
        live_sufficiency: LiveSufficiencyState | None = None
        if sufficiency_policy is not None:
            live_sufficiency = evaluate_live_sufficiency(data_quality, sufficiency_policy, generated_at)

        sample_count = data_quality.sample_count
        cutover_note = f"sample_count ({sample_count}) is below minimum_samples ({minimum_samples})"
        if sample_count == 0:
            # Phase 10: no telemetry at all → NO_DATA. There is nothing to score,
            # so the assessment cannot exist yet (contrast with LIMITED_DATA).
            findings = [
                Finding(
                    rule_id=INSUFFICIENT_DATA_RULE,
                    severity="info",
                    category="data_quality",
                    metric=None,
                    message="No telemetry samples in the analysis window; no health assessment is possible.",
                    confidence=0.5,
                    window_start=window.start,
                    window_end=window.end,
                )
            ]
            score_details = insufficient_score(notes=[cutover_note])
            confidence = None
            data_sufficiency = "no_data"
            provisional = False
            provisional_rating = None
        elif sample_count < minimum_samples or (
            live_sufficiency is not None and not live_sufficiency.policy_met
        ):
            # Phase 10: LIMITED_DATA. Evaluate the rules on whatever telemetry
            # exists so the first sample already yields a provisional rating,
            # but keep the definitive status honest (limited data, low
            # confidence) instead of presenting it as a firm verdict. For a
            # live current-session evaluation the sufficiency gate failure is
            # reported explicitly (collecting_data) with its own evidence.
            findings = self._rule_engine.evaluate(
                statistics=statistics,
                data_quality=data_quality,
                window=window,
                expected_interval_seconds=expected_interval_seconds,
            )
            findings.append(
                Finding(
                    rule_id=LIMITED_DATA_RULE,
                    severity="info",
                    category="data_quality",
                    metric=None,
                    message=(
                        "Limited telemetry: this is a provisional assessment with low "
                        "confidence, not a definitive verdict."
                    ),
                    confidence=0.5,
                    window_start=window.start,
                    window_end=window.end,
                )
            )
            if live_sufficiency is not None and not live_sufficiency.policy_met:
                findings.append(
                    Finding(
                        rule_id=LIVE_SUFFICIENCY_RULE,
                        severity="info",
                        category="data_quality",
                        metric=None,
                        message=(
                            "Current-session evidence is still being collected; "
                            "this live assessment is provisional, not definitive."
                        ),
                        confidence=0.5,
                        evidence={
                            "reasons": live_sufficiency.reasons,
                            "sample_count": live_sufficiency.sample_count,
                            "required_sample_count": live_sufficiency.required_sample_count,
                            "observation_duration_seconds": (
                                live_sufficiency.observation_duration_seconds
                            ),
                            "required_duration_seconds": live_sufficiency.required_duration_seconds,
                            "coverage_ratio": live_sufficiency.coverage_ratio,
                            "required_coverage": live_sufficiency.required_coverage,
                            "latest_sample_age_seconds": live_sufficiency.latest_sample_age_seconds,
                            "max_sample_age_seconds": live_sufficiency.max_sample_age_seconds,
                        },
                        window_start=window.start,
                        window_end=window.end,
                    )
                )
            findings.sort(key=lambda f: (f.rule_id, f.severity))
            score_details = score_findings(findings)
            confidence = compute_confidence(data_quality, statistics, window)
            data_sufficiency = "limited_data"
            provisional = True
            provisional_rating = score_details.status
        else:
            findings = self._rule_engine.evaluate(
                statistics=statistics,
                data_quality=data_quality,
                window=window,
                expected_interval_seconds=expected_interval_seconds,
            )
            score_details = score_findings(findings)
            confidence = compute_confidence(data_quality, statistics, window)
            data_sufficiency = "sufficient_data"
            provisional = False
            provisional_rating = None

        baselines = []
        if history and sample_count > 0 and len(history) >= baseline_minimum:
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
            data_sufficiency=data_sufficiency,
            provisional=provisional,
            provisional_rating=provisional_rating,
            simulation_run_id=simulation_run_id,
            live_sufficiency=live_sufficiency,
        )
        logger.info(
            "health analysis: vehicle_id=%s samples=%s sufficiency=%s provisional=%s "
            "rating=%s status=%s score=%s findings=%s coverage=%s duration_ms=%s",
            vehicle_id,
            data_quality.sample_count,
            data_sufficiency,
            provisional,
            provisional_rating,
            score_details.status,
            score_details.score,
            len(findings),
            data_quality.coverage_ratio,
            duration_ms,
        )
        return context
