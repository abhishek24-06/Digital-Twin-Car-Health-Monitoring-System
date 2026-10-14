"""Markdown/JSON rendering for evaluation results (plan §10).

Every rendered report carries an explicit provenance tag and the RQ2/RQ5
limitations verbatim so a number can never be read out of context.
"""

from __future__ import annotations

from typing import Any

LIMITATIONS: tuple[str, ...] = (
    "SYNTHETIC ONLY: telemetry comes from the in-repo simulator; this is not "
    "real-world validation.",
    "No independent continuous health reference exists; RQ2 is ordinal "
    "discrimination only (no MAE/RMSE/R2).",
    "No expert-labelled reference diagnoses exist; RQ5 correctness is NOT "
    "EVALUABLE (only the grounding contract can be measured).",
    "The analyzer is deterministic rule logic, not a learned classifier; "
    "'accuracy' means agreement with injected conditions.",
    "The 'full' view includes cold-start warm-up and is expected to raise "
    "false-positive rapid-rise findings.",
    "Only four simulator scenarios exist; rules without an injected positive "
    "control cannot be validated here.",
)


def _render_view(lines: list[str], view_name: str, view: dict[str, Any]) -> None:
    role = (
        "PRIMARY fault-detection view"
        if view_name == "steady"
        else "warm-up-sensitivity / false-positive view"
    )
    lines.append(f"## RQ1 fault detection — `{view_name}` ({role})")
    lines.append("")
    lines.append(f"Episodes: {view['n_episodes']}")
    lines.append("")

    lines.append("### Per-episode expected-rule detection")
    lines.append("")
    lines.append("| scenario | reference family | episodes | detected expected | false-positive episodes |")
    lines.append("|---|---|---|---|---|")
    for scenario, bucket in view["rq1_per_scenario"].items():
        lines.append(
            f"| {scenario} | {bucket['reference_family']} | {bucket['n_episodes']} | "
            f"{bucket['detected_expected']} | {bucket['false_positive_episodes']} |"
        )
    lines.append("")

    lines.append("### Alert-worthy rule frequency")
    lines.append("")
    lines.append("| scenario | alert-worthy rule | episodes |")
    lines.append("|---|---|---|")
    for scenario, bucket in view["rq1_per_scenario"].items():
        counts = bucket.get("alert_worthy_rule_counts") or {}
        if not counts:
            lines.append(f"| {scenario} | _(none)_ | 0 |")
        for rule_id, count in sorted(counts.items()):
            lines.append(f"| {scenario} | {rule_id} | {count} |")
    lines.append("")

    detection = view["rq1_detection"]
    labels = list(detection["labels"])
    lines.append("### Family classification")
    lines.append("")
    lines.append(f"- accuracy: {_pct(detection.get('accuracy'))}")
    lines.append(f"- macro-F1: {_pct(detection.get('macro_f1'))}")
    lines.append(f"- weighted-F1: {_pct(detection.get('weighted_f1'))}")
    lines.append("")
    lines.append("| true \\ pred | " + " | ".join(labels) + " |")
    lines.append("|" + "---|" * (len(labels) + 1))
    for true_label in labels:
        row = detection["confusion_matrix"][true_label]
        lines.append(f"| {true_label} | " + " | ".join(str(row[c]) for c in labels) + " |")
    lines.append("")

    lines.append("### Per-label precision / recall / F1")
    lines.append("")
    lines.append("| label | support | predicted | precision | recall | F1 |")
    lines.append("|---|---|---|---|---|---|")
    for label, metrics in detection["per_label"].items():
        support = int(metrics["support"])
        predicted = int(metrics["predicted"])
        if support == 0 and predicted == 0:
            continue
        lines.append(
            f"| {label} | {support} | {predicted} | {_pct(metrics['precision'])} | "
            f"{_pct(metrics['recall'])} | {_pct(metrics['f1'])} |"
        )
    lines.append("")

    rq2 = view["rq2_health"]
    lines.append("### RQ2 — ordinal health discrimination (no regression metrics)")
    lines.append("")
    lines.append(f"- {rq2['note']}")
    lines.append(f"- AUC (anomaly vs. normal): {_pct(rq2.get('auc_anomaly_vs_normal'))} "
                 f"(n_anomaly={view['rq2_health'].get('n_anomaly')}, "
                 f"n_normal={view['rq2_health'].get('n_normal')})")
    lines.append(f"- AUC (thermal vs. non-thermal): {_pct(view['rq2_health'].get('auc_thermal_vs_nonthermal'))}")
    lines.append("")
    lines.append("| reference family | n | min | median | max | mean |")
    lines.append("|---|---|---|---|---|---|")
    for family, dist in view["rq2_health"]["score_by_reference_family"].items():
        lines.append(
            f"| {family} | {dist['count']} | {dist['min']} | {dist['median']} | "
            f"{dist['max']} | {dist['mean']} |"
        )
    lines.append("")
    lines.append("Status confusion (partly circular — status buckets share thresholds):")
    lines.append("")
    for family, row in view["rq2_health"]["status_confusion_partly_circular"].items():
        rendered = ", ".join(f"{status}: {count}" for status, count in sorted(row.items()))
        lines.append(f"- {family}: {rendered}")
    lines.append("")

    latency = view.get("rq4_compute_latency_ms") or {}
    if latency:
        lines.append("### RQ4 compute latency (software, MEASURED)")
        lines.append("")
        lines.append(f"- {latency.get('note', '')}")
        stats = latency.get("analysis") or {}
        if stats.get("count"):
            lines.append(f"- analysis_duration_ms: {_latency_line(stats)}")
        lines.append("")


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _num(value: float | int | bool | None) -> str:
    """Render one latency number exactly as stored (never re-rounds)."""
    if value is None:
        return "n/a"
    return str(value)


def _latency_line(stats: dict[str, Any]) -> str:
    """Render a latency summary as a single deterministic, single-source line.

    Every value comes straight from ``stats`` (the same dict persisted to
    ``metrics.json``); no number is recomputed here. Percentiles that the sample
    count cannot justify are labelled rather than silently shown as the maximum.
    """
    p95 = f"p95={_num(stats.get('p95'))}"
    if stats.get("p95_justified") is False:
        p95 += " (not justified: n<20)"
    p99 = f"p99={_num(stats.get('p99'))}"
    if stats.get("p99_justified") is False:
        p99 += " (not justified: n<100)"
    return (
        f"n={stats['count']} min={_num(stats.get('min'))} "
        f"p50={_num(stats.get('p50'))} {p95} {p99} "
        f"max={_num(stats.get('max'))} mean={_num(stats.get('mean'))}"
    )


def render_markdown(report: dict[str, Any]) -> str:
    """Render the full evaluation report as Markdown."""
    lines: list[str] = []
    lines.append(f"# Accuracy Evaluation — `{report.get('dataset_id')}`")
    lines.append("")
    lines.append(f"**Provenance tag:** `{report.get('provenance_tag', 'SIMULATED')}`")
    lines.append(f"**Generated:** {report.get('generated_at')}")
    lines.append("")
    lines.append("This report is **simulated** (synthetic telemetry). It is not a")
    lines.append("real-world accuracy claim. See the limitations at the end.")
    lines.append("")

    commands = report.get("commands") or []
    if commands:
        lines.append("## Commands executed")
        lines.append("")
        for command in commands:
            lines.append(f"- `{command}`")
        lines.append("")

    manifest = report.get("manifest") or {}
    if manifest:
        lines.append("## Dataset provenance")
        lines.append("")
        lines.append(f"- dataset_id: `{manifest.get('dataset_id')}`")
        lines.append(f"- generator: `{manifest.get('generator')}`")
        lines.append(f"- reference_source: {manifest.get('reference_source')}")
        lines.append(f"- label_method: {manifest.get('label_method')}")
        lines.append(f"- label_version: {manifest.get('label_version')}")
        lines.append(f"- code_revision: `{manifest.get('code_revision')}`")
        lines.append(f"- episodes: {len(manifest.get('episodes') or [])}")
        lines.append(f"- provenance: {report.get('provenance_tag')}")
        lines.append("")

    views = report.get("views") or {}
    for view_name, view in views.items():
        _render_view(lines, view_name, view)

    lines.append("## RQ2 / RQ5 status")
    lines.append("")
    lines.append(
        "- **RQ2 (health vs. independent reference):** SIMULATED, ordinal only. No "
        "independent continuous health reference exists, so no MAE/RMSE/R2 is "
        "reported and AUC must not be read as accuracy."
    )
    lines.append(
        "- **RQ5 (AI diagnosis correctness):** NOT EVALUABLE. No expert-labelled "
        "reference diagnoses exist; only the grounding contract can be measured."
    )
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    for limitation in report.get("limitations") or LIMITATIONS:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


__all__ = ["LIMITATIONS", "render_markdown"]
