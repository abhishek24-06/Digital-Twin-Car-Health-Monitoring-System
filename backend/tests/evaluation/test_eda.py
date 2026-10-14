"""Hermetic tests for the post-hoc EDA (``evaluation.eda``).

These build tiny in-memory datasets; they never read the real result sets, a
database or a broker, and they never write outside ``tmp_path``. They pin the
contract that matters for honesty: the EDA follows the frozen nearest-rank
percentile policy, suppresses unjustifiable percentiles, and renders the report
strictly from the serialized summary mapping.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from evaluation.eda import analysis, figures, report

FEATURES = list(analysis.FEATURES)
SCENARIOS = ("normal", "high_temperature", "low_battery")


def _point(scenario: str, index: int) -> dict:
    values = {
        "rpm": 800.0,
        "speed": 0.0,
        "engine_load": 10.0,
        "coolant_temperature": 20.0 + index + (40.0 if scenario == "high_temperature" else 0.0),
        "oil_temperature": 20.0 + index,
        "battery_voltage": 14.0 if scenario != "low_battery" else 11.0,
        "fuel_level": 90.0,
        "intake_air_temperature": 15.0,
        "throttle_position": 5.0,
        "engine_runtime": float(index),
        "odometer": float(index),
    }
    return {"offset_seconds": float(index), "values": values}


def _dataset() -> dict:
    episodes = []
    for scenario in SCENARIOS:
        for seed in (1, 2):
            episodes.append(
                {
                    "provenance": {
                        "episode_id": f"{scenario}-{seed}",
                        "scenario": scenario,
                        "seed": seed,
                        "reference_family": "thermal"
                        if scenario == "high_temperature"
                        else ("electrical" if scenario == "low_battery" else "none"),
                    },
                    "points": [_point(scenario, index) for index in range(20)],
                }
            )
    return {"dataset_id": "test-v1", "manifest": {"code_revision": "deadbeef"}, "episodes": episodes}


def _episodes() -> list[dict]:
    rows = []
    for scenario in SCENARIOS:
        for seed in (1, 2):
            for view in ("steady", "full"):
                rules = ["RAPID_COOLANT_RISE"] if scenario == "high_temperature" else []
                rows.append(
                    {
                        "episode_id": f"{scenario}-{seed}",
                        "scenario": scenario,
                        "seed": seed,
                        "view": view,
                        "predicted_family": "thermal" if scenario == "high_temperature" else "none",
                        "reference_family": "thermal"
                        if scenario == "high_temperature"
                        else ("electrical" if scenario == "low_battery" else "none"),
                        "rule_ids": rules if view == "full" else [],
                        "health_status": "warning" if scenario != "normal" else "ok",
                        "health_score": 40.0 if scenario == "high_temperature" else 90.0,
                        "confidence": 0.9,
                        "data_sufficiency": "sufficient",
                        "analysis_duration_ms": 1.2,
                    }
                )
    return rows


def _scenarios_metrics() -> dict:
    return {
        "views": {
            "steady": {
                "rq1_detection": {
                    "accuracy": 1.0,
                    "macro_f1": 1.0,
                    "weighted_f1": 1.0,
                    "labels": ["none", "thermal"],
                    "confusion_matrix": {"none": {"none": 4, "thermal": 0}, "thermal": {"none": 0, "thermal": 2}},
                },
                "rq2_health": {
                    "auc_anomaly_vs_normal": 1.0,
                    "auc_thermal_vs_nonthermal": 0.9,
                    "n_anomaly": 2,
                    "n_normal": 4,
                    "score_by_reference_family": {"none": {"median": 90.0}},
                    "status_confusion_partly_circular": {"ok": 4},
                },
                "rq4_compute_latency_ms": {"analysis": {"p50": 1.2, "count": 12}},
            },
            "full": {
                "rq1_detection": {
                    "accuracy": 0.8,
                    "macro_f1": 0.7,
                    "weighted_f1": 0.8,
                    "labels": ["none", "thermal"],
                    "confusion_matrix": {"none": {"none": 3, "thermal": 1}, "thermal": {"none": 0, "thermal": 2}},
                },
                "rq2_health": {
                    "auc_anomaly_vs_normal": 0.8,
                    "auc_thermal_vs_nonthermal": 0.7,
                    "n_anomaly": 2,
                    "n_normal": 4,
                    "score_by_reference_family": {"none": {"median": 80.0}},
                    "status_confusion_partly_circular": {"warning": 2, "ok": 4},
                },
                "rq4_compute_latency_ms": {"analysis": {"p50": 1.4, "count": 12}},
            },
        },
        "episodes": _episodes(),
    }


def _pipeline_metrics() -> dict:
    per_episode = []
    for scenario in SCENARIOS:
        for seed in (1, 2):
            alerts = ["RAPID_COOLANT_RISE"] if scenario == "high_temperature" else []
            per_episode.append(
                {
                    "episode_id": f"{scenario}-{seed}",
                    "scenario": scenario,
                    "seed": seed,
                    "reference_family": "thermal" if scenario == "high_temperature" else "none",
                    "detected": scenario == "high_temperature",
                    "alerts": alerts,
                    "matching_alerts": alerts,
                    "false_positive_alerts": [],
                    "monitor_passes": 6,
                    "failed_passes": 0,
                    "snapshots_persisted": 6,
                }
            )
    return {
        "meta": {"dataset_id": "test-pipeline-v1"},
        "alerts": {
            "summary": {
                "episodes": 6,
                "detected_episode_ids": ["high_temperature-1", "high_temperature-2"],
                "episode_recall": 1.0,
                "episode_precision": 1.0,
                "expected_rule_recall": 1.0,
                "expected_rule_pairs": 2,
                "expected_rule_pairs_hit": 2,
                "alerts_matching": 2,
                "alerts_false_positive": 0,
                "alert_precision": 1.0,
                "false_alarms_per_vehicle_hour": 0.0,
                "duplicate_alert_rows": 0,
                "alerts_provisional_at_create": 2,
                "alerts_definitive_at_create": 0,
                "per_episode": per_episode,
            },
            "recovery": {
                "cases": [
                    {
                        "scenario": "high_temperature",
                        "expected_rule_ids": ["RAPID_COOLANT_RISE"],
                        "resolved_rule_ids": ["RAPID_COOLANT_RISE"],
                        "ttr_seconds": 30.0,
                    }
                ]
            },
        },
        "latency": {
            "samples": [
                {
                    "ingest_ms": 3.0 + index,
                    "engine_analysis_duration_ms": 1.0 + index * 0.1,
                    "monitor_pass_ms": 10.0 + index,
                    "analysis_scope": "current_session",
                    "provisional": False,
                }
                for index in range(5)
            ],
            "alert_latencies": [
                {"publish_to_alert_ms": 20.0, "rule_id": "RAPID_COOLANT_RISE"},
                {"publish_to_alert_ms": 30.0, "rule_id": "RAPID_COOLANT_RISE"},
            ],
        },
        "robustness": {
            "cases": [
                {
                    "case": "transient_db_failure",
                    "persisted": 5,
                    "expected_range": [5, 5],
                    "passed": True,
                    "description": "subscriber retries",
                    "detail": "ok",
                },
                {
                    "case": "broker_restart",
                    "persisted": 5,
                    "expected_range": [5, 5],
                    "passed": True,
                    "description": "publisher reopen",
                    "detail": "ok",
                },
            ]
        },
    }


def _summary() -> dict:
    dataset = _dataset()
    telemetry = analysis.telemetry_frame(dataset)
    episodes = analysis.episodes_frame(_scenarios_metrics())
    inputs = {"dataset_id": "test-v1", "n_episodes": 6, "points": 120}
    return analysis.clean(
        analysis.summarize(telemetry, episodes, _scenarios_metrics(), _pipeline_metrics(), inputs)
    )


# --------------------------------------------------------------------------- #
def test_telemetry_frame_shape() -> None:
    frame = analysis.telemetry_frame(_dataset())
    assert len(frame) == 6 * 20
    assert list(analysis.FEATURES) == [f for f in FEATURES]
    for feature in FEATURES:
        assert feature in frame.columns
    assert set(frame["scenario"]) == set(SCENARIOS)


def test_eta_squared_separates_and_detects_flat_channels() -> None:
    frame = analysis.telemetry_frame(_dataset())
    eta = analysis.eta_squared(frame)
    # coolant differs by scenario -> strongly separated.
    assert eta["coolant_temperature"] > 0.9
    # fuel_level is identical in every scenario -> no separation.
    assert eta["fuel_level"] == pytest.approx(0.0, abs=1e-9)


def test_stats_follows_frozen_nearest_rank_policy() -> None:
    stats = analysis._stats([10.0, 20.0, 30.0])
    assert stats["count"] == 3
    assert stats["p50"] == 20.0
    # n < MIN_SAMPLES_FOR_P95 -> p95 must be suppressed, never printed.
    assert stats["p95"] is None


def test_stats_reports_p95_when_justified() -> None:
    stats = analysis._stats([float(value) for value in range(100)])
    assert stats["count"] == 100
    assert stats["p95"] is not None


def test_clean_is_json_safe() -> None:
    payload = {"n": np.int64(3), "x": np.float64(1.5), "bad": np.float64("nan"), "flag": np.bool_(True)}
    cleaned = analysis.clean(payload)
    assert cleaned == {"n": 3, "x": 1.5, "bad": None, "flag": True}
    json.dumps(cleaned)  # must not raise


def test_summarize_structure() -> None:
    summary = _summary()
    for key in (
        "meta",
        "inputs",
        "telemetry",
        "rq1_detection",
        "rq2_health",
        "rq3_alerts",
        "rq4_latency",
        "rq6_robustness",
        "findings_by_view",
    ):
        assert key in summary
    assert summary["telemetry"]["n_points"] == 120
    assert summary["rq6_robustness"]["passed"] == 2
    # EDA must carry its provenance disclaimer.
    assert "post-hoc" in summary["meta"]["analysis"]
    # findings are separated per view (full view emits the rapid-rise rule).
    assert summary["findings_by_view"]["steady"] == {}
    assert summary["findings_by_view"]["full"]["RAPID_COOLANT_RISE"] == 2


def test_report_renders_from_summary() -> None:
    summary = _summary()
    markdown = report.render_markdown(summary)
    assert markdown.startswith("# Exploratory Data Analysis")
    for heading in ("## 1. Inputs & scope", "## 5. RQ3", "## 9. Figure index", "## 10. Limitations"):
        assert heading in markdown
    assert "eta-squared" in markdown
    # Unjustified percentiles (n=2 here) must render as n/a, not a number.
    alert_row = next(line for line in markdown.splitlines() if line.startswith("| publish to alert (ms)"))
    assert "n/a" in alert_row


def test_report_is_single_source_from_json_roundtrip() -> None:
    summary = _summary()
    # Rendering must depend only on the serialized mapping.
    reloaded = json.loads(json.dumps(summary))
    assert report.render_markdown(reloaded) == report.render_markdown(summary)


def test_render_all_writes_figures(tmp_path) -> None:
    dataset = _dataset()
    telemetry = analysis.telemetry_frame(dataset)
    episodes = analysis.episodes_frame(_scenarios_metrics())
    pipeline = _pipeline_metrics()
    frames = {
        "telemetry": telemetry,
        "episodes": episodes,
        "alerts": analysis.alerts_frame(pipeline),
        "latency": analysis.latency_frame(pipeline),
        "alert_latency": analysis.alert_latency_frame(pipeline),
        "robustness": analysis.robustness_frame(pipeline),
    }
    summary = _summary()
    written = figures.render_all(frames, summary, tmp_path)
    assert written
    for name in written:
        path = tmp_path / name
        assert path.exists()
        assert path.stat().st_size > 0
