"""Aggregate analyzer results into the pre-registered RQ1/RQ2 metrics (plan §6).

Pure functions over :class:`evaluation.runner.EpisodeResult`. Keeps the
integrity-critical logic (which findings count, how families are reduced, what
counts as a detection) in one reviewable place.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from evaluation.metrics.detection import classification_report
from evaluation.metrics.health import roc_auc, score_distribution, status_confusion
from evaluation.metrics.latency import summarize_latency
from evaluation.registry import FAMILY_PRECEDENCE, severity_at_least
from evaluation.runner import EpisodeResult

CLASS_LABELS: list[str] = list(FAMILY_PRECEDENCE)

RQ2_NOTE = (
    "No independent continuous health reference exists; regression metrics "
    "(MAE/RMSE/R2) are intentionally NOT computed. AUC is ordinal discrimination "
    "of the injected condition, not accuracy. The status confusion is descriptive "
    "and partly circular (status buckets and rules share thresholds)."
)


def is_alert_worthy(finding: dict[str, Any]) -> bool:
    """Mirror of ``AlertService.is_alert_worthy``: warning/critical, non-data-quality."""
    severity = finding.get("severity")
    rule_id = finding.get("rule_id")
    return severity in ("warning", "critical") and isinstance(rule_id, str) and finding.get(
        "category"
    ) != "data_quality"


def _aggregate(selected: list[EpisodeResult]) -> dict[str, Any]:
    per_scenario: dict[str, dict[str, Any]] = {}
    for result in selected:
        bucket = per_scenario.setdefault(
            result.scenario,
            {
                "n_episodes": 0,
                "reference_family": result.reference_family,
                "detected_expected": 0,
                "false_positive_episodes": 0,
                "hit_rules": {},
                "alert_worthy_rule_counts": {},
            },
        )
        bucket["n_episodes"] += 1

        worthy = [f for f in result.findings if is_alert_worthy(f)]
        for finding in worthy:
            rule_id = str(finding.get("rule_id"))
            counts = bucket["alert_worthy_rule_counts"]
            counts[rule_id] = counts.get(rule_id, 0) + 1

        if result.reference_family == "none":
            if worthy:
                bucket["false_positive_episodes"] += 1
        else:
            expected = set(result.expected_rule_ids)
            matched = {
                str(f.get("rule_id"))
                for f in result.findings
                if severity_at_least(str(f.get("severity")), result.expected_min_severity)
            }
            if expected & matched:
                bucket["detected_expected"] += 1
                for rule_id in sorted(expected & matched):
                    hits = bucket["hit_rules"]
                    hits[rule_id] = hits.get(rule_id, 0) + 1

    pairs = [(r.reference_family, r.predicted_family) for r in selected]
    scores = [r.health_score for r in selected]
    anomalies = [r.reference_family != "none" for r in selected]
    thermal = [r.reference_family == "thermal" for r in selected]

    return {
        "n_episodes": len(selected),
        "rq1_detection": classification_report(pairs, CLASS_LABELS),
        "rq1_per_scenario": per_scenario,
        "rq4_compute_latency_ms": {
            "note": (
                "MEASURED software compute latency of HealthAnalysisEngine.analyze per "
                "episode (analysis_duration_ms). Publish-to-alert pipeline latency "
                "requires the isolated MQTT+DB harness and is NOT measured here."
            ),
            "analysis": summarize_latency([r.analysis_duration_ms for r in selected]),
        },
        "rq2_health": {
            "note": RQ2_NOTE,
            "auc_anomaly_vs_normal": roc_auc(scores, anomalies),
            "auc_thermal_vs_nonthermal": roc_auc(scores, thermal),
            "n_anomaly": sum(1 for a in anomalies if a),
            "n_normal": sum(1 for a in anomalies if not a),
            "score_by_reference_family": {
                family: score_distribution(
                    [r.health_score for r in selected if r.reference_family == family]
                )
                for family in CLASS_LABELS
                if any(r.reference_family == family for r in selected)
            },
            "status_confusion_partly_circular": status_confusion(
                [r.reference_family for r in selected],
                [r.health_status for r in selected],
            ),
        },
    }


def evaluate_view(results: Iterable[EpisodeResult], view: str) -> dict[str, Any]:
    """Aggregate one analysis view. Raises if the view has no results."""
    selected = [r for r in results if r.view == view]
    if not selected:
        raise ValueError(f"no results for view {view!r}")
    return _aggregate(selected)


def evaluate(results: Iterable[EpisodeResult], views: Iterable[str] = ("steady", "full")) -> dict[str, Any]:
    """Aggregate every requested view present in the result set."""
    materialized = list(results)
    out: dict[str, Any] = {}
    for view in views:
        if any(r.view == view for r in materialized):
            out[view] = _aggregate([r for r in materialized if r.view == view])
    return out


__all__ = ["CLASS_LABELS", "RQ2_NOTE", "is_alert_worthy", "evaluate"]
