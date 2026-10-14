"""Run the *shipped* deterministic analyzer over generated episodes (plan §5).

This module imports :class:`app.intelligence.engine.HealthAnalysisEngine` and
evaluates it exactly as production does; it never copies or modifies the
algorithm. Two analysis views are produced per episode (plan §4.1.1):

* ``steady`` — the primary fault-detection view (post-warm-up suffix);
* ``full``   — the warm-up-sensitivity / false-positive view (whole episode).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

from app.intelligence.engine import HealthAnalysisEngine
from app.intelligence.models import AnalysisWindow, TelemetryPoint
from evaluation.registry import primary_family, rules_to_family
from evaluation.scenarios import Episode, ScenarioSpec, steady_suffix

#: Hard minimum the engine needs before it will call an assessment definitive.
MINIMUM_SAMPLES = 10


@dataclass
class EpisodeResult:
    """One analyzer evaluation of one episode in one view."""

    episode_id: str
    dataset_id: str
    scenario: str
    seed: int
    reference_family: str
    view: str
    predicted_family: str
    predicted_families: list[str]
    findings: list[dict[str, Any]]
    health_status: str
    health_score: float | None
    confidence: float | None
    data_sufficiency: str
    provisional: bool
    sample_count: int
    window_seconds: float
    analysis_duration_ms: float | None
    expected_rule_ids: tuple[str, ...] = field(default_factory=tuple)
    expected_min_severity: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "dataset_id": self.dataset_id,
            "scenario": self.scenario,
            "seed": self.seed,
            "reference_family": self.reference_family,
            "view": self.view,
            "predicted_family": self.predicted_family,
            "predicted_families": self.predicted_families,
            "rule_ids": [f.get("rule_id") for f in self.findings],
            "health_status": self.health_status,
            "health_score": self.health_score,
            "confidence": self.confidence,
            "data_sufficiency": self.data_sufficiency,
            "provisional": self.provisional,
            "sample_count": self.sample_count,
            "window_seconds": self.window_seconds,
            "analysis_duration_ms": self.analysis_duration_ms,
            "expected_rule_ids": list(self.expected_rule_ids),
            "expected_min_severity": self.expected_min_severity,
        }


def _analyze_view(
    episode: Episode, spec: ScenarioSpec, view: str, points: list[TelemetryPoint]
) -> EpisodeResult:
    provenance = episode.provenance
    if points:
        window = AnalysisWindow(
            start=points[0].timestamp,
            end=points[-1].timestamp,
            window_minutes=(points[-1].timestamp - points[0].timestamp).total_seconds() / 60.0,
        )
    else:
        window = AnalysisWindow(start=provenance.created_at, end=provenance.created_at, window_minutes=0.0)

    engine = HealthAnalysisEngine()
    context = engine.analyze(
        vehicle_id=UUID(provenance.run_id),
        window=window,
        samples=points,
        history=[],
        minimum_samples=MINIMUM_SAMPLES,
        expected_interval_seconds=spec.interval_seconds,
        baseline_minimum_samples=5,
        generated_at=window.end + timedelta(seconds=1),
    )

    findings = [finding.model_dump(mode="json") for finding in context.findings]
    return EpisodeResult(
        episode_id=provenance.episode_id,
        dataset_id=provenance.dataset_id,
        scenario=provenance.scenario,
        seed=provenance.seed,
        reference_family=provenance.reference_family,
        view=view,
        predicted_family=primary_family(findings),
        predicted_families=[str(f) for f in rules_to_family(findings)],
        findings=findings,
        health_status=str(context.health_status),
        health_score=context.health_score,
        confidence=context.confidence,
        data_sufficiency=str(context.data_sufficiency),
        provisional=bool(context.provisional),
        sample_count=context.data_quality.sample_count,
        window_seconds=round(window.duration_seconds, 3),
        analysis_duration_ms=context.analysis_duration_ms,
        expected_rule_ids=provenance.expected_rule_ids,
        expected_min_severity=provenance.expected_min_severity,
    )


def analyze_episode(episode: Episode, spec: ScenarioSpec) -> list[EpisodeResult]:
    """Evaluate one episode in both pre-registered views."""
    full = _analyze_view(episode, spec, "full", episode.points)
    steady_points = steady_suffix(episode.points, spec)
    steady = _analyze_view(episode, spec, "steady", steady_points)
    return [steady, full]


__all__ = ["EpisodeResult", "MINIMUM_SAMPLES", "analyze_episode"]
