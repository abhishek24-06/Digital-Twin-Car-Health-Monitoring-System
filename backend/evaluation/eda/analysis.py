"""Exploratory data analysis over the frozen evaluation artifacts.

This module is **post-hoc and exploratory**: it is *not* part of the frozen
pre-registration (``docs/research/accuracy_evaluation_plan.md``) and computes no
scored metric. It only *describes* the synthetic telemetry and the already
recorded evaluation results, so every quantity here carries the same provenance
as its source: ``SIMULATED`` for telemetry, ``MEASURED`` for pipeline behaviour.

Keeping EDA separate from the frozen protocol is deliberate: exploring the data
must never be able to rewrite a scored result (see
``docs/research/evaluation_final_report.md`` §3).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from evaluation.metrics.latency import (
    MIN_SAMPLES_FOR_P95,
)
from evaluation.metrics.latency import (
    percentile as _percentile,
)

#: Telemetry channels produced by ``SimulationEngine`` (order is stable in the
#: dataset; kept explicit so the EDA never silently picks up a renamed field).
FEATURES: tuple[str, ...] = (
    "rpm",
    "speed",
    "engine_load",
    "coolant_temperature",
    "oil_temperature",
    "battery_voltage",
    "fuel_level",
    "intake_air_temperature",
    "throttle_position",
    "engine_runtime",
    "odometer",
)

#: Human labels for a few channels (figures/report only).
FEATURE_LABELS: dict[str, str] = {
    "coolant_temperature": "coolant temp",
    "oil_temperature": "oil temp",
    "intake_air_temperature": "intake air temp",
    "battery_voltage": "battery voltage",
    "engine_load": "engine load",
    "engine_runtime": "engine runtime",
    "throttle_position": "throttle position",
    "fuel_level": "fuel level",
    "engine_speed": "engine speed",
}


# --------------------------------------------------------------------------- #
# Loading / hashing
# --------------------------------------------------------------------------- #
def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value: Any) -> Any:
    """Recursively convert numpy/pandas scalars to JSON-safe Python values."""
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else round(float(value), 6)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float):
        return None if value != value else round(value, 6)
    return value


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean(obj: Any) -> Any:
    """Recursively convert numpy/pandas scalars to JSON-safe Python values."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return None if np.isnan(obj) else round(float(obj), 6)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float):
        return None if obj != obj else round(obj, 6)
    return obj


# --------------------------------------------------------------------------- #
# Frames
# --------------------------------------------------------------------------- #
def telemetry_frame(dataset: dict[str, Any]) -> pd.DataFrame:
    """One row per (episode, second) with the telemetry channels as columns."""
    rows: list[dict[str, Any]] = []
    for episode in dataset["episodes"]:
        meta = episode["provenance"]
        for index, point in enumerate(episode["points"]):
            values = point["values"]
            row: dict[str, Any] = {
                "episode_id": meta["episode_id"],
                "scenario": meta["scenario"],
                "seed": meta["seed"],
                "reference_family": meta["reference_family"],
                "t": index,
            }
            for feature in FEATURES:
                row[feature] = values.get(feature)
            rows.append(row)
    return pd.DataFrame(rows)


def episodes_frame(metrics: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(metrics["episodes"])
    frame["n_rules"] = frame["rule_ids"].apply(len)
    return frame


def alerts_frame(pipeline_metrics: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in pipeline_metrics["alerts"]["summary"]["per_episode"]:
        rows.append(
            {
                "episode_id": row["episode_id"],
                "scenario": row["scenario"],
                "seed": row["seed"],
                "reference_family": row["reference_family"],
                "detected": bool(row["detected"]),
                "n_alerts": len(row["alerts"]),
                "n_matching": len(row["matching_alerts"]),
                "n_false_positive": len(row["false_positive_alerts"]),
                "monitor_passes": row["monitor_passes"],
                "failed_passes": row["failed_passes"],
                "snapshots_persisted": row["snapshots_persisted"],
            }
        )
    return pd.DataFrame(rows)


def latency_frame(pipeline_metrics: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(pipeline_metrics["latency"]["samples"])


def alert_latency_frame(pipeline_metrics: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(pipeline_metrics["latency"].get("alert_latencies") or [])


def robustness_frame(pipeline_metrics: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for case in pipeline_metrics["robustness"]["cases"]:
        expected = case.get("expected_range") or [None, None]
        rows.append(
            {
                "case": case["case"],
                "persisted": case["persisted"],
                "expected_min": expected[0],
                "expected_max": expected[1],
                "passed": bool(case["passed"]),
                "description": case.get("description", ""),
                "detail": case.get("detail", ""),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Statistics helpers
# --------------------------------------------------------------------------- #
def _stats(values: Any) -> dict[str, Any]:
    series = pd.Series(values, dtype="float64").dropna()
    if series.empty:
        return {
            "count": 0,
            "min": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p95": None,
            "max": None,
            "mean": None,
            "std": None,
        }
    ordered = [float(value) for value in series]
    # Nearest-rank percentiles, matching evaluation.metrics.latency (no
    # interpolation) so EDA summaries agree with the frozen report. p95 is only
    # reported when n >= MIN_SAMPLES_FOR_P95, exactly like the frozen policy.
    return {
        "count": int(series.size),
        "min": float(series.min()),
        "p25": _percentile(ordered, 0.25),
        "p50": _percentile(ordered, 0.50),
        "p75": _percentile(ordered, 0.75),
        "p95": _percentile(ordered, 0.95) if series.size >= MIN_SAMPLES_FOR_P95 else None,
        "max": float(series.max()),
        "mean": float(series.mean()),
        "std": float(series.std(ddof=1)) if series.size > 1 else 0.0,
    }


def eta_squared(frame: pd.DataFrame, group: str = "scenario") -> dict[str, float]:
    """Fraction of each feature's variance explained by the scenario label.

    A one-way eta-squared (0 = no separation, 1 = perfect separation). This is a
    descriptive effect size for *which channels carry the injected fault*, not a
    significance test.
    """
    out: dict[str, float] = {}
    for feature in FEATURES:
        if feature not in frame:
            continue
        values = frame[feature].astype("float64")
        grand = values.mean()
        total = float(((values - grand) ** 2).sum())
        if total <= 0:
            out[feature] = 0.0
            continue
        between = 0.0
        for _, chunk in values.groupby(frame[group]):
            between += len(chunk) * (chunk.mean() - grand) ** 2
        out[feature] = float(between / total)
    return out


def _top_correlations(corr: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    pairs = []
    columns = list(corr.columns)
    for i, left in enumerate(columns):
        for right in columns[i + 1 :]:
            value = float(corr.loc[left, right])
            if np.isnan(value):
                continue
            pairs.append({"left": left, "right": right, "r": value})
    pairs.sort(key=lambda item: abs(item["r"]), reverse=True)
    return pairs[:limit]


def _describe_frame(frame: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    return {column: _stats(frame[column]) for column in columns if column in frame}


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
def summarize(
    telemetry: pd.DataFrame,
    episodes: pd.DataFrame,
    scenarios_metrics: dict[str, Any],
    pipeline_metrics: dict[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Build the full, JSON-serializable EDA summary."""
    alerts = alerts_frame(pipeline_metrics)
    latency = latency_frame(pipeline_metrics)
    alert_latency = alert_latency_frame(pipeline_metrics)
    robustness = robustness_frame(pipeline_metrics)

    corr = telemetry[list(FEATURES)].astype("float64").corr()
    eta = eta_squared(telemetry)
    constant_features = [
        feature
        for feature in FEATURES
        if float(telemetry[feature].astype("float64").std(ddof=0)) <= 1e-9
    ]

    scenario_means = (
        telemetry.groupby("scenario")[list(FEATURES)].mean().round(4).to_dict(orient="index")
    )
    episodes_per_scenario = (
        telemetry.groupby("scenario")["episode_id"].nunique().sort_index().to_dict()
    )
    points_by_scenario = telemetry.groupby("scenario").size().sort_index().to_dict()

    # Warm-up trajectories (mean over episodes), downsampled every 5 s.
    warmup: dict[str, Any] = {"t": [], "series": {}}
    sampled = sorted(t for t in telemetry["t"].unique() if t % 5 == 0)
    warmup["t"] = [int(t) for t in sampled]
    for channel in ("coolant_temperature", "oil_temperature"):
        warmup["series"][channel] = {}
        pivot = telemetry[telemetry["t"].isin(sampled)].groupby(["scenario", "t"])[channel].mean()
        for scenario in sorted(telemetry["scenario"].unique()):
            warmup["series"][channel][scenario] = [
                round(float(pivot.loc[(scenario, t)]), 3) if (scenario, t) in pivot.index else None
                for t in sampled
            ]

    # Findings (rule ids observed per episode), split by analysis view.
    findings: dict[str, dict[str, int]] = {}
    for view in sorted(episodes["view"].unique()):
        counter: Counter[str] = Counter()
        for rules in episodes.loc[episodes["view"] == view, "rule_ids"]:
            counter.update(rules)
        findings[view] = dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))

    # RQ1 detection + RQ2 health, per view (read straight from the frozen metrics).
    views = scenarios_metrics.get("views", {})
    rq1 = {
        view: {
            "accuracy": data["rq1_detection"].get("accuracy"),
            "macro_f1": data["rq1_detection"].get("macro_f1"),
            "weighted_f1": data["rq1_detection"].get("weighted_f1"),
            "labels": data["rq1_detection"].get("labels"),
            "confusion": data["rq1_detection"].get("confusion_matrix"),
        }
        for view, data in views.items()
    }
    rq2 = {
        view: {
            "auc_anomaly_vs_normal": data["rq2_health"].get("auc_anomaly_vs_normal"),
            "auc_thermal_vs_nonthermal": data["rq2_health"].get("auc_thermal_vs_nonthermal"),
            "n_anomaly": data["rq2_health"].get("n_anomaly"),
            "n_normal": data["rq2_health"].get("n_normal"),
            "score_by_reference_family": data["rq2_health"].get("score_by_reference_family"),
            "status": data["rq2_health"].get("status_confusion_partly_circular"),
        }
        for view, data in views.items()
    }

    # RQ4: compute latency (accuracy run) alongside streaming latency (pipeline run).
    compute_latency = {
        view: data["rq4_compute_latency_ms"].get("analysis") for view, data in views.items()
    }
    rq4 = {
        "compute_ms": compute_latency,
        "streaming_ingest_ms": _stats(latency.get("ingest_ms")) if not latency.empty else None,
        "streaming_engine_ms": _stats(latency.get("engine_analysis_duration_ms"))
        if not latency.empty
        else None,
        "streaming_monitor_pass_ms": _stats(latency.get("monitor_pass_ms"))
        if not latency.empty
        else None,
        "publish_to_alert_ms": _stats(alert_latency.get("publish_to_alert_ms"))
        if not alert_latency.empty
        else None,
    }

    # RQ3 alert outcome tables.
    rq3 = {
        "summary": {
            key: value
            for key, value in pipeline_metrics["alerts"]["summary"].items()
            if key not in ("per_episode", "detected_episode_ids")
        },
        "per_episode": alerts.to_dict(orient="records"),
        "recovery": pipeline_metrics["alerts"]["recovery"],
    }

    summary = {
        "meta": {
            "analysis": "exploratory data analysis (post-hoc, NOT pre-registered)",
            "provenance": "SIMULATED telemetry + MEASURED pipeline behaviour",
            "notes": [
                "EDA describes the frozen evaluation artifacts; it computes no scored metric.",
                "The reference label is the injected scenario, not an independent sensor.",
                "Differences here are descriptive, not statistical significance tests.",
            ],
        },
        "inputs": inputs,
        "telemetry": {
            "n_points": int(len(telemetry)),
            "n_episodes": int(telemetry["episode_id"].nunique()),
            "points_per_episode": int(telemetry.groupby("episode_id").size().max()),
            "n_features": len(FEATURES),
            "features": list(FEATURES),
            "constant_features": constant_features,
            "overall": _describe_frame(telemetry, list(FEATURES)),
            "by_scenario_means": scenario_means,
            "episodes_per_scenario": episodes_per_scenario,
            "points_by_scenario": points_by_scenario,
            "eta_squared": eta,
            "correlation": {
                "labels": list(corr.columns),
                "matrix": corr.round(4).values.tolist(),
                "top_pairs": _top_correlations(corr),
            },
            "warmup": warmup,
        },
        "rq1_detection": rq1,
        "rq2_health": rq2,
        "rq3_alerts": rq3,
        "rq4_latency": rq4,
        "rq6_robustness": {
            "cases": robustness.to_dict(orient="records"),
            "passed": int(robustness["passed"].sum()),
            "total": int(len(robustness)),
        },
        "findings_by_view": findings,
        "episodes": episodes.to_dict(orient="records"),
    }
    return summary
