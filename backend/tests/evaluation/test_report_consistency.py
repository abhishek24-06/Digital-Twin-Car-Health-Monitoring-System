"""Report/metrics consistency regression tests (plan §5, §10).

These are hermetic: they never touch a database, broker or the network. They
guard the single-source contract — the Markdown report must render exactly the
values stored in ``metrics.json`` — and the arithmetic invariants of the
detection aggregates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.__main__ import (
    assert_not_frozen,
    render_from_metrics,
    run,
    write_metrics_and_report,
)
from evaluation.metrics.detection import classification_report
from evaluation.metrics.latency import MIN_SAMPLES_FOR_P95, MIN_SAMPLES_FOR_P99, summarize_latency
from evaluation.report import render_markdown

LABELS = ["thermal", "electrical", "engine_load", "engine_speed", "fuel", "none"]


# --------------------------------------------------------------------------- #
# Latency summarisation: consistent rounding + percentile justification
# --------------------------------------------------------------------------- #


def test_latency_summary_rounds_every_field() -> None:
    stats = summarize_latency([1.23456, 2.34567, 3.45678])
    for key in ("min", "p50", "max", "mean"):
        assert isinstance(stats[key], float)
        assert stats[key] == round(stats[key], 3)  # type: ignore[arg-type]


def test_p95_justified_at_twenty_samples_only() -> None:
    below = summarize_latency([float(i) for i in range(MIN_SAMPLES_FOR_P95 - 1)])
    assert below["count"] == MIN_SAMPLES_FOR_P95 - 1
    assert below["p95"] is None
    assert below["p95_justified"] is False
    assert below["max"] == float(MIN_SAMPLES_FOR_P95 - 2)

    # At exactly the threshold the percentile is justified and, with evenly
    # spaced samples, must not collapse to the maximum (unlike a naive p99).
    at_threshold = summarize_latency([float(i) for i in range(MIN_SAMPLES_FOR_P95)])
    assert at_threshold["p95_justified"] is True
    assert at_threshold["p95"] == 18.0
    assert at_threshold["p95"] != at_threshold["max"]


def test_p99_not_justified_below_one_hundred_samples() -> None:
    small = summarize_latency([float(i) for i in range(MIN_SAMPLES_FOR_P99 - 1)])
    assert small["p99"] is None
    assert small["p99_justified"] is False
    # A smaller series must not be allowed to present its maximum as a p99.
    assert small["max"] is not None

    large = summarize_latency([float(i) for i in range(MIN_SAMPLES_FOR_P99)])
    assert large["p99_justified"] is True
    assert large["p99"] == 98.0


# --------------------------------------------------------------------------- #
# Detection aggregate invariants
# --------------------------------------------------------------------------- #


def test_detection_aggregates_are_mutually_consistent() -> None:
    pairs = [
        ("thermal", "thermal"),
        ("thermal", "none"),
        ("electrical", "electrical"),
        ("engine_load", "thermal"),
        ("none", "none"),
        ("none", "thermal"),
    ]
    report = classification_report(pairs, LABELS)
    matrix = report["confusion_matrix"]
    labels = report["labels"]
    n = sum(sum(row.values()) for row in matrix.values())
    assert n == report["n_episodes"] == len(pairs)

    # Accuracy is the trace over n.
    trace = sum(matrix[label][label] for label in labels)
    assert report["accuracy"] == pytest.approx(trace / n)

    # Per-label support/predicted equal the matrix row/column sums.
    for label in labels:
        row = sum(matrix[label].values())
        column = sum(matrix[other][label] for other in labels)
        metrics = report["per_label"][label]
        assert metrics["support"] == row
        assert metrics["predicted"] == column

    # Macro-F1 is the unweighted mean over supported/predicted labels; weighted
    # F1 is support-weighted over supported labels.
    scored = [
        m for m in report["per_label"].values() if m["support"] > 0 or m["predicted"] > 0
    ]
    assert report["macro_f1"] == pytest.approx(sum(m["f1"] for m in scored) / len(scored))
    supported = [m for m in report["per_label"].values() if m["support"] > 0]
    total = sum(m["support"] for m in supported)
    weighted = sum(m["support"] * m["f1"] for m in supported) / total
    assert report["weighted_f1"] == pytest.approx(weighted)


# --------------------------------------------------------------------------- #
# Single-source rendering
# --------------------------------------------------------------------------- #


def _example_report() -> dict:
    detection = classification_report(
        [("thermal", "thermal"), ("none", "none")], LABELS
    )
    return {
        "dataset_id": "unit-test",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "provenance_tag": "SIMULATED",
        "manifest": {"dataset_id": "unit-test", "episodes": []},
        "views": {
            "steady": {
                "n_episodes": 2,
                "rq1_per_scenario": {},
                "rq1_detection": detection,
                "rq2_health": {
                    "note": "ordinal only",
                    "auc_anomaly_vs_normal": 1.0,
                    "n_anomaly": 1,
                    "n_normal": 1,
                    "auc_thermal_vs_nonthermal": 1.0,
                    "score_by_reference_family": {
                        "thermal": {"count": 1, "min": 60, "median": 60, "max": 60, "mean": 60.0}
                    },
                    "status_confusion_partly_circular": {"thermal": {"attention": 1}},
                },
                "rq4_compute_latency_ms": {
                    "note": "MEASURED",
                    "analysis": summarize_latency([1.0, 2.0, 3.0]),
                },
            }
        },
        "manifest_limitations": [],
    }


def test_report_renders_exactly_the_metrics_values(tmp_path: Path) -> None:
    report = _example_report()
    out_dir = tmp_path / "ds"
    out_dir.mkdir()
    write_metrics_and_report(out_dir, report)

    metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    markdown = (out_dir / "REPORT.md").read_text(encoding="utf-8")

    stats = metrics["views"]["steady"]["rq4_compute_latency_ms"]["analysis"]
    # The exact stored values must appear in the report; nothing recomputed.
    assert f"p50={stats['p50']}" in markdown
    assert f"max={stats['max']}" in markdown
    assert f"mean={stats['mean']}" in markdown
    # p95/p99 are not justified at n=3 and must be labelled, never silently
    # rendered as the maximum.
    assert "p95=n/a" in markdown
    assert "p99=n/a" in markdown
    assert "not justified" in markdown

    # Re-rendering from the serialized JSON reproduces the file byte-for-byte.
    render_from_metrics(out_dir)
    assert (out_dir / "REPORT.md").read_text(encoding="utf-8") == markdown
    assert markdown == render_markdown(metrics)


def test_cli_run_metrics_agree_with_per_episode_rows(tmp_path, monkeypatch) -> None:
    import evaluation.__main__ as cli

    monkeypatch.setattr(cli, "RESULTS_ROOT", tmp_path)
    out_dir = run(
        dataset_id="consistency",
        scenarios=("normal", "high_temperature"),
        seeds=(1,),
        command="pytest",
        action="all",
    )
    metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    episodes = metrics["episodes"]

    for view_name, view in metrics["views"].items():
        rows = [e for e in episodes if e["view"] == view_name]
        # RQ4 recomputation from the per-episode rows.
        recomputed = summarize_latency([e["analysis_duration_ms"] for e in rows])
        assert view["rq4_compute_latency_ms"]["analysis"] == recomputed

        # Detection accuracy from the confusion matrix.
        detection = view["rq1_detection"]
        matrix = view["rq1_detection"]["confusion_matrix"]
        labels = view["rq1_detection"]["labels"]
        n = sum(sum(row.values()) for row in matrix.values())
        trace = sum(matrix[label][label] for label in labels)
        assert view["rq1_detection"]["n_episodes"] == len(rows) == view["n_episodes"]
        assert detection["accuracy"] == pytest.approx(trace / n)
        for label in labels:
            assert view["rq1_detection"]["per_label"][label]["support"] == sum(
                view["rq1_detection"]["confusion_matrix"][label].values()
            )

    # The report is a pure function of the metrics bytes.
    assert (out_dir / "REPORT.md").read_text(encoding="utf-8") == render_markdown(metrics)


# --------------------------------------------------------------------------- #
# Frozen-dataset write guard
# --------------------------------------------------------------------------- #


def test_frozen_dataset_guard_blocks_changed_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "synthetic-scenarios-v1"
    out_dir.mkdir()
    (out_dir / "PLAN_HASHES.json").write_text(
        json.dumps(
            {
                "dataset_id": "synthetic-scenarios-v1",
                "files": {
                    "backend/evaluation/metrics/latency.py": "0" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception) as excinfo:
        assert_not_frozen(out_dir, force=False)
    assert "frozen" in str(excinfo.value).lower()
    # An explicit force is honoured.
    assert_not_frozen(out_dir, force=True)
