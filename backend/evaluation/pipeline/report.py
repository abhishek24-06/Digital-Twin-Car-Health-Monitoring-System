"""Markdown rendering for the pipeline evaluation (single source of truth).

Like :mod:`evaluation.report`, this module renders **strictly from the serialized
``metrics.json`` mapping**. It computes no measurement of its own, so the report
and the JSON it claims to describe cannot disagree.
"""

from __future__ import annotations

from typing import Any

#: Fixed limitation text (plan §10). Never fabricated per-run.
PIPELINE_LIMITATIONS: tuple[str, ...] = (
    "Synthetic telemetry produced by the in-repo simulator; this is a SIMULATED "
    "systems evaluation, not real-vehicle validation.",
    "The reference label is the scenario the harness injected, not an independent "
    "sensor or engineering ground truth.",
    "Alert quality is measured on the live current-session path only; historical "
    "windowed analyses are documented as never creating alerts, not scored.",
    "Publish-to-alert latency here means publish -> persisted alert row on one host "
    "with a monotonic clock; it excludes network hops outside this machine.",
    "Recovery (time-to-resolution) is modelled with a second, condition-free session "
    "on the same vehicle because a single fault episode cannot self-resolve.",
)


def _num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _latency_line(stats: dict[str, Any] | None, *, unit: str = "ms") -> str:
    """Render one latency series, labelling unjustified percentiles as such."""
    if not stats:
        return "no data"
    parts = [
        f"n={stats.get('count', 0)}",
        f"min={_num(stats.get('min'))}",
        f"p50={_num(stats.get('p50'))}",
    ]
    if stats.get("p95_justified"):
        parts.append(f"p95={_num(stats.get('p95'))}")
    else:
        parts.append("p95=n/a (not justified: n<20)")
    if stats.get("p99_justified"):
        parts.append(f"p99={_num(stats.get('p99'))}")
    else:
        parts.append("p99=n/a (not justified: n<100)")
    parts.extend([f"max={_num(stats.get('max'))}", f"mean={_num(stats.get('mean'))}"])
    return f"{' '.join(parts)} [{unit}]"


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _alert_section(metrics: dict[str, Any]) -> list[str]:
    alerts = metrics.get("alerts") or {}
    summary = alerts.get("summary") or {}
    if not summary:
        return ["## RQ3 — Alert lifecycle", "", "_Not executed in this run._", ""]
    lines = [
        "## RQ3 — Alert lifecycle (live current-session path)",
        "",
        f"- Episodes: {summary.get('episodes', 0)} "
        f"({summary.get('positive_episodes', 0)} fault, "
        f"{summary.get('episodes', 0) - summary.get('positive_episodes', 0)} control), "
        f"exposure {_num(summary.get('exposure_hours'), 4)} vehicle-hours.",
        f"- Episode recall: {_pct(summary.get('episode_recall'))} "
        f"({summary.get('episodes_detected', 0)}/"
        f"{summary.get('positive_episodes', 0)}); "
        f"episode precision: {_pct(summary.get('episode_precision'))}.",
        f"- Expected-rule recall: {_pct(summary.get('expected_rule_recall'))} "
        f"({summary.get('expected_rule_pairs_hit', 0)}/"
        f"{summary.get('expected_rule_pairs', 0)} episode-rule pairs).",
        f"- Alerts: {summary.get('alerts_total', 0)} total, "
        f"{summary.get('alerts_matching', 0)} matching, "
        f"{summary.get('alerts_false_positive', 0)} false positive; "
        f"alert precision {_pct(summary.get('alert_precision'))}.",
        f"- False alarms: {_num(summary.get('false_alarms_per_vehicle_hour'))} per "
        f"vehicle-hour.",
        f"- Duplicate alert rows: {summary.get('duplicate_alert_rows', 0)}; "
        f"recurrence-folded updates: {summary.get('recurrence_updates_total', 0)}.",
        f"- Alerts provisional at creation: "
        f"{summary.get('alerts_provisional_at_create', 0)}; definitive: "
        f"{summary.get('alerts_definitive_at_create', 0)}.",
        f"- Time to first detection: "
        f"{_latency_line(summary.get('time_to_first_detection_seconds'), unit='s')}",
        f"- Unresolved within-episode alerts: {summary.get('unresolved_alerts', 0)} "
        f"(a single fault episode cannot self-resolve).",
        "",
    ]
    missed = summary.get("missed_episode_ids") or []
    if missed:
        lines += [f"- **Missed episodes**: {', '.join(missed)}", ""]

    lines += [
        "### Per-episode outcome",
        "",
        "| episode | scenario | reference | expected rules | alerts | matching | false positive | detected |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary.get("per_episode", []):
        lines.append(
            "| {ep} | {sc} | {fam} | {exp} | {alerts} | {match} | {fp} | {det} |".format(
                ep=row.get("episode_id"),
                sc=row.get("scenario"),
                fam=row.get("reference_family"),
                exp=", ".join(row.get("expected_rule_ids", [])) or "(none)",
                alerts=", ".join(row.get("alerts", [])) or "(none)",
                match=", ".join(row.get("matching_alerts", [])) or "(none)",
                fp=", ".join(row.get("false_positive_alerts", [])) or "(none)",
                det="yes" if row.get("detected") else "no",
            )
        )
    lines.append("")

    scope = alerts.get("scope_counts") or {}
    if scope:
        lines += [
            "### Snapshot scope fed to the alert path",
            "",
            "Every snapshot passed to `AlertService.sync_from_snapshot` must be a "
            "`current_session` evaluation (historical windowed analyses never create "
            "alerts).",
            "",
            "| analysis_scope | snapshots |",
            "| --- | --- |",
        ]
        for key, value in sorted(scope.items()):
            lines.append(f"| {key} | {value} |")
        lines.append("")

    recovery = alerts.get("recovery") or {}
    rsummary = recovery.get("summary") or {}
    if rsummary:
        lines += [
            "### Recovery (time to resolution)",
            "",
            "A condition-free `normal` session runs on the same vehicle after each fault "
            "episode; a definitive pass that no longer observes the rule auto-resolves it.",
            "",
            f"- Cases: {rsummary.get('episodes', 0)}; resolved fault-rule alerts: "
            f"{rsummary.get('time_to_resolution_n', 0)}.",
            f"- Time to resolution: "
            f"{_latency_line(rsummary.get('time_to_resolution_seconds'), unit='s')}",
            "",
            "| scenario | fault rules | resolved fault rules | TTR (s) |",
            "| --- | --- | --- | --- |",
        ]
        for case in recovery.get("cases", []):
            lines.append(
                "| {sc} | {exp} | {res} | {ttr} |".format(
                    sc=case.get("scenario"),
                    exp=", ".join(case.get("expected_rule_ids", [])) or "(none)",
                    res=", ".join(case.get("resolved_rule_ids", [])) or "(none)",
                    ttr=_num(case.get("ttr_seconds")),
                )
            )
        lines.append("")
    return lines


def _latency_section(metrics: dict[str, Any]) -> list[str]:
    latency = metrics.get("latency") or {}
    if not latency:
        return ["## RQ4 — Pipeline latency", "", "_Not executed in this run._", ""]
    lines = [
        "## RQ4 — Pipeline latency (wall clock, single host, monotonic)",
        "",
        f"- Wall-clock samples: {latency.get('n_samples', 0)}; "
        f"new alerts observed: {latency.get('n_alerts', 0)}; "
        f"monitor failures: {len(latency.get('failures', []))}.",
        "",
        "| stage | series |",
        "| --- | --- |",
        f"| publish -> persisted telemetry row | "
        f"{_latency_line(latency.get('ingest_ms'))} |",
        f"| engine self-reported analyse duration | "
        f"{_latency_line(latency.get('engine_analysis_duration_ms'))} |",
        f"| monitor pass (analyse + alert sync) | "
        f"{_latency_line(latency.get('monitor_pass_ms'))} |",
        f"| publish -> alert persisted | "
        f"{_latency_line(latency.get('publish_to_alert_ms'))} |",
        "",
        "`publish → detection` and `publish -> alert` are the same instant here: a "
        "finding is materialised into a persisted alert synchronously in the same "
        "monitor pass, so the two are reported as one number rather than two.",
        "",
    ]
    if latency.get("n_alerts", 0) < 100:
        lines += [
            "- Publish-to-alert percentiles are not justified at this sample count; only "
            "the median should be used. Increase seed count/session length to justify p95/p99.",
            "",
        ]
    if latency.get("failures"):
        lines += ["### Failures", ""]
        lines += [f"- {f}" for f in latency["failures"]]
        lines.append("")
    return lines


def _robustness_section(metrics: dict[str, Any]) -> list[str]:
    robustness = metrics.get("robustness") or {}
    cases = robustness.get("cases") or []
    if not cases:
        return ["## RQ6 — Robustness under injected faults", "", "_Not executed in this run._", ""]
    lines = [
        "## RQ6 — Robustness under injected delivery/DB/broker faults",
        "",
        f"- Cases: {len(cases)}; passed: {sum(1 for c in cases if c.get('passed'))}"
        f"/{len(cases)}.",
        "",
        "| case | persisted | expected | passed | description | detail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in cases:
        lines.append(
            "| {case} | {persisted} | {expected} | {passed} | {desc} | {detail} |".format(
                case=row.get("case"),
                persisted=_num(row.get("persisted"), 0),
                expected="…".join(str(x) for x in (row.get("expected_range") or [])),
                passed="yes" if row.get("passed") else "no",
                desc=row.get("description", ""),
                detail=row.get("detail", ""),
            )
        )
    lines.append("")
    return lines


def _environment_block(metrics: dict[str, Any]) -> list[str]:
    environment = metrics.get("environment") or {}
    if not environment:
        return []
    lines = [
        "## Environment",
        "",
        f"- Platform: {environment.get('platform')}; Python {environment.get('python')}",
        f"- Database: {environment.get('database_name')} on {environment.get('database_host')} "
        "(disposable, loopback, fail-closed)",
        f"- Broker: {environment.get('broker_host')}:{environment.get('broker_port')} "
        "(private mosquitto, persistence false)",
        f"- MQTT batch: max {environment.get('mqtt_batch_max_messages')} message(s) / "
        f"{environment.get('mqtt_batch_flush_seconds')} s flush",
        f"- Analysis window: {environment.get('analysis_window_minutes')} min; "
        f"interval {environment.get('expected_interval_seconds')} s",
        "",
        "Clock semantics:",
    ]
    for key, value in (environment.get("clock_semantics") or {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    return lines


def render_markdown(metrics: dict[str, Any]) -> str:
    """Render the pipeline report strictly from the metrics mapping."""
    meta = metrics.get("meta") or {}
    status = meta.get("status", "UNKNOWN")
    lines = [
        f"# Digital Twin pipeline evaluation — RQ3/RQ4/RQ6 ({status})",
        "",
        f"- Dataset id: `{meta.get('dataset_id', 'unknown')}`",
        f"- Generated: {meta.get('generated_at', 'unknown')}",
        f"- Provenance: {meta.get('provenance', 'unknown')}",
        f"- Code revision: `{meta.get('code_revision', 'unknown')}`",
        "",
    ]
    if status != "EXECUTED":
        lines += [
            "> This result set was **not executed**. It records a precondition failure "
            "rather than any measurement; no metric below should be read as a result.",
            "",
            f"> Blocker: {meta.get('blocker', 'unknown')}",
            "",
        ]
        return "\n".join(lines) + "\n"

    lines += _alert_section(metrics)
    lines += _latency_section(metrics)
    lines += _robustness_section(metrics)
    lines += _environment_section_guard(metrics)
    lines += [
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in PIPELINE_LIMITATIONS]
    lines.append("")
    return "\n".join(lines) + "\n"


#: Thin wrapper so the environment block is emitted once with a stable heading.
def _environment_section_guard(metrics: dict[str, Any]) -> list[str]:
    meta = metrics.get("meta") or {}
    environment = metrics.get("environment") or {}
    lines: list[str] = ["## Run provenance", ""]
    for command in meta.get("commands", []) or []:
        lines.append(f"- `{command}`")
    lines.append("")
    lines += _environment_block(metrics)
    if not environment:
        lines += ["_Environment not recorded._", ""]
    return lines


__all__ = ["PIPELINE_LIMITATIONS", "render_markdown"]
