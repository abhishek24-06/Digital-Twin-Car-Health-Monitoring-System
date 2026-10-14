"""Render ``EDA.md`` strictly from the serialized ``eda_metrics.json`` mapping.

Like the evaluation reports, this renderer computes no measurement of its own:
it only formats the mapping produced by :mod:`evaluation.eda.analysis`, so the
report and the JSON cannot disagree.
"""

from __future__ import annotations

from typing import Any

FIGURES: tuple[tuple[str, str], ...] = (
    ("fig01_feature_separability.png", "Channels ranked by scenario-explained variance (eta-squared)."),
    ("fig02_scenario_profile.png", "Standardised per-scenario channel means."),
    ("fig03_correlation.png", "Pearson correlation between channels."),
    ("fig04_warmup.png", "Cold-start warm-up ramp (coolant & oil temperature)."),
    ("fig05_feature_distributions.png", "Per-scenario telemetry distributions."),
    ("fig06_health_scores.png", "Health score by injected family and view."),
    ("fig07_rq1_confusion.png", "RQ1 detection confusion by view."),
    ("fig08_findings.png", "Findings emitted per view."),
    ("fig09_latency.png", "Pipeline latency distributions."),
    ("fig10_alert_outcomes.png", "RQ3 per-episode alert outcomes."),
    ("fig11_robustness.png", "RQ6 persisted vs expected rows."),
)


def _fmt(value: Any, places: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def _stats_row(name: str, stats: dict[str, Any] | None) -> str:
    if not stats:
        return f"| {name} | – | – | – | – | – | – |"
    return "| {name} | {n} | {min} | {p50} | {p95} | {max} | {mean} |".format(
        name=name,
        n=_fmt(stats.get("count")),
        min=_fmt(stats.get("min"), 3),
        p50=_fmt(stats.get("p50"), 3),
        p95=_fmt(stats.get("p95"), 3),
        max=_fmt(stats.get("max"), 3),
        mean=_fmt(stats.get("mean"), 3),
    )


def render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    meta = summary.get("meta") or {}
    inputs = summary.get("inputs") or {}
    telemetry = summary.get("telemetry") or {}

    lines += [
        "# Exploratory Data Analysis — Digital Twin evaluation",
        "",
        f"**Provenance: {meta.get('provenance', 'SIMULATED + MEASURED')}.** This EDA is",
        "**post-hoc and exploratory**; it is *not* the frozen pre-registration and it",
        "computes no scored metric. It only describes the synthetic telemetry and the",
        "already-recorded results, so it can never rewrite a scored finding.",
        "",
    ]

    # ------------------------------------------------------------------ inputs
    lines += ["## 1. Inputs & scope", "", "| Input | Value |", "| --- | --- |"]
    for key in (
        "dataset_id",
        "code_revision",
        "scope",
        "generated_at",
        "n_episodes",
        "points",
        "features",
        "pipeline_dataset_id",
    ):
        if key in inputs:
            lines.append(f"| {key} | {_fmt(inputs[key])} |")
    lines.append("")
    if inputs.get("sources"):
        lines += ["Input file hashes (sha256):", ""]
        for name, record in inputs["sources"].items():
            lines.append(f"- `{name}` — {record.get('sha256')} ({record.get('bytes')} bytes)")
        lines.append("")

    # --------------------------------------------------------------- telemetry
    lines += [
        "## 2. Telemetry dataset EDA (SIMULATED)",
        "",
        f"- Points: {_fmt(telemetry.get('n_points'))} "
        f"({_fmt(telemetry.get('n_episodes'))} episodes x "
        f"{_fmt(telemetry.get('points_per_episode'))} s x "
        f"{_fmt(telemetry.get('n_features'))} channels).",
        f"- Episodes per scenario: {telemetry.get('episodes_per_scenario')}.",
        f"- Points per scenario: {telemetry.get('points_by_scenario')}.",
        f"- Constant channels (no variance): {telemetry.get('constant_features') or 'none'}.",
        "",
        "### 2.1 Channel summary", "",
        "| channel | n | min | p50 | p95 | max | mean |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for feature in telemetry.get("features", []):
        lines.append(_stats_row(feature, (telemetry.get("overall") or {}).get(feature)))
    lines.append("")

    eta = telemetry.get("eta_squared") or {}
    if eta:
        ordered = sorted(eta, key=lambda key: eta[key], reverse=True)
        lines += [
            "### 2.2 Scenario separability (one-way eta-squared)", "",
            "Fraction of each channel's variance explained by the injected scenario.",
            "Descriptive effect size only — not a significance test.",
            "",
            "| channel | eta-squared |",
            "| --- | --- |",
        ]
        for feature in ordered:
            lines.append(f"| {feature} | {_fmt(eta[feature])} |")
        lines.append("")

    top = (telemetry.get("correlation") or {}).get("top_pairs") or []
    if top:
        lines += ["### 2.3 Strongest channel correlations", "", "| pair | r |", "| --- | --- |"]
        for pair in top:
            lines.append(f"| {pair['left']} ~ {pair['right']} | {_fmt(pair['r'])} |")
        lines.append("")

    warm = telemetry.get("warmup") or {}
    if warm.get("series"):
        coolant = (warm["series"].get("coolant_temperature") or {}).get("normal") or []
        if coolant and coolant[0] is not None and coolant[-1] is not None:
            lines += [
                "### 2.4 Warm-up ramp observation", "",
                f"On the `normal` scenario the mean coolant temperature rises from "
                f"~{_fmt(coolant[0], 1)} deg C at t=0 to ~{_fmt(coolant[-1], 1)} deg C by "
                f"t={warm['t'][-1]} s. A cold start is itself a rapid rise, which is why the "
                "`RAPID_*` rules fire during warm-up (see fig04 and RQ1 `full` view).",
                "",
            ]

    # -------------------------------------------------------------------- RQ1
    lines += ["## 3. RQ1 — detection (from the frozen accuracy run)", "", "| view | accuracy | macro-F1 | weighted-F1 |", "| --- | --- | --- | --- |"]
    for view, row in (summary.get("rq1_detection") or {}).items():
        lines.append(f"| {view} | {_fmt(row.get('accuracy'))} | {_fmt(row.get('macro_f1'))} | {_fmt(row.get('weighted_f1'))} |")
    lines.append("")

    # -------------------------------------------------------------------- RQ2
    lines += ["## 4. RQ2 — health assessment (ordinal only)", "", "| view | AUC(anomaly vs normal) | AUC(thermal vs non-thermal) |", "| --- | --- | --- |"]
    for view, row in (summary.get("rq2_health") or {}).items():
        lines.append(f"| {view} | {_fmt(row.get('auc_anomaly_vs_normal'))} | {_fmt(row.get('auc_thermal_vs_nonthermal'))} |")
    lines.append("")
    lines += ["Health score by family (steady / full medians):", ""]
    families: dict[str, dict[str, Any]] = {}
    for view, row in (summary.get("rq2_health") or {}).items():
        for family, stats in (row.get("score_by_reference_family") or {}).items():
            families.setdefault(family, {})[view] = stats.get("median")
    lines += ["| family | steady median | full median |", "| --- | --- | --- |"]
    for family in ["none", "thermal", "electrical", "engine_load"]:
        if family in families:
            lines.append(f"| {family} | {_fmt(families[family].get('steady'))} | {_fmt(families[family].get('full'))} |")
    lines.append("")

    # -------------------------------------------------------------------- RQ3
    rq3 = summary.get("rq3_alerts") or {}
    s = rq3.get("summary") or {}
    lines += [
        "## 5. RQ3 — alert lifecycle (live path)",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| episodes | {_fmt(s.get('episodes'))} |",
        f"| episode recall | {_fmt(s.get('episode_recall'))} |",
        f"| episode precision | {_fmt(s.get('episode_precision'))} |",
        f"| expected-rule recall | {_fmt(s.get('expected_rule_recall'))} "
        f"({_fmt(s.get('expected_rule_pairs_hit'))}/{_fmt(s.get('expected_rule_pairs'))}) |",
        f"| alerts (matching / false positive) | {_fmt(s.get('alerts_matching'))} / {_fmt(s.get('alerts_false_positive'))} |",
        f"| alert precision | {_fmt(s.get('alert_precision'))} |",
        f"| false alarms per vehicle-hour | {_fmt(s.get('false_alarms_per_vehicle_hour'))} |",
        f"| duplicate alert rows | {_fmt(s.get('duplicate_alert_rows'))} |",
        f"| provisional / definitive at create | {_fmt(s.get('alerts_provisional_at_create'))} / {_fmt(s.get('alerts_definitive_at_create'))} |",
        "",
    ]
    per_episode = rq3.get("per_episode") or []
    if per_episode:
        lines += [
            "### 5.1 Per-episode alert outcome", "",
            "| episode | scenario | reference | detected | matching | false positive |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in per_episode:
            lines.append(
                f"| {row['episode_id']} | {row['scenario']} | {row['reference_family']} | "
                f"{_fmt(row['detected'])} | {_fmt(row['n_matching'])} | {_fmt(row['n_false_positive'])} |"
            )
        lines.append("")
    recovery = rq3.get("recovery") or {}
    cases = recovery.get("cases") or []
    if cases:
        lines += ["### 5.2 Recovery", "", "| scenario | expected rules | resolved rules | TTR (s) |", "| --- | --- | --- | --- |"]
        for case in cases:
            lines.append(
                f"| {case['scenario']} | {', '.join(case.get('expected_rule_ids') or []) or '(none)'} | "
                f"{', '.join(case.get('resolved_rule_ids') or []) or '(none)'} | {_fmt(case.get('ttr_seconds'))} |"
            )
        lines.append("")

    # -------------------------------------------------------------------- RQ4
    rq4 = summary.get("rq4_latency") or {}
    lines += [
        "## 6. RQ4 — pipeline latency (MEASURED)",
        "",
        "| stage | n | min | p50 | p95 | max | mean |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        _stats_row("publish to persisted row (ms)", rq4.get("streaming_ingest_ms")),
        _stats_row("engine analyse (ms)", rq4.get("streaming_engine_ms")),
        _stats_row("monitor pass (ms)", rq4.get("streaming_monitor_pass_ms")),
        _stats_row("publish to alert (ms)", rq4.get("publish_to_alert_ms")),
        "",
        "Compute latency from the accuracy run: "
        + ", ".join(
            f"{view} p50 {_fmt((stats or {}).get('p50'))} ms"
            for view, stats in (rq4.get("compute_ms") or {}).items()
        )
        + ".",
        "",
    ]

    # -------------------------------------------------------------------- RQ6
    rq6 = summary.get("rq6_robustness") or {}
    lines += [
        "## 7. RQ6 — robustness (injected faults)",
        "",
        f"Passed {_fmt(rq6.get('passed'))}/{_fmt(rq6.get('total'))} injected-fault cases.",
        "",
        "| case | persisted | expected | passed |",
        "| --- | --- | --- | --- |",
    ]
    for case in rq6.get("cases") or []:
        expected = f"{_fmt(case.get('expected_min'))}..{_fmt(case.get('expected_max'))}"
        lines.append(f"| {case['case']} | {_fmt(case.get('persisted'))} | {expected} | {_fmt(case.get('passed'))} |")
    lines.append("")

    # --------------------------------------------------------- cross-cutting
    lines += [
        "## 8. Cross-cutting observations (descriptive)",
        "",
        "- The rapid-rise rules fire on the plain warm-up ramp in every view that",
        "  includes the ramp; the `steady` view (ramp excluded) is clean. This is the",
        "  same cold-start false-positive mechanism reported in the alert results.",
        "- Between-scenario separability is concentrated in a few channels (see the",
        "  eta-squared ranking); most channels overlap heavily across scenarios.",
        "- Health score and status move together with the emitted findings, so the",
        "  status distribution is descriptive and partly circular, not independent.",
        "- Latency distributions are right-skewed; medians are the honest summary and",
        "  p95/p99 are only meaningful where n is large enough.",
        "",
    ]

    # ---------------------------------------------------------------- figures
    lines += ["## 9. Figure index", ""]
    for filename, caption in FIGURES:
        lines += [f"### {filename}", "", caption, "", f"![{filename}](figures/{filename})", ""]

    lines += [
        "## 10. Limitations",
        "",
        "- Telemetry is **simulated** by the in-repo generator; this is not real data.",
        "- Reference labels are the injected scenarios, not independent sensor labels.",
        "- The EDA is descriptive: no hypothesis test is applied and no p-value is",
        "  reported; differences between groups are not claimed to be significant.",
        "- EDA is explicitly outside the frozen pre-registration and must never be",
        "  cited as a scored result.",
        "",
    ]
    return "\n".join(lines) + "\n"


__all__ = ["render_markdown", "FIGURES"]
