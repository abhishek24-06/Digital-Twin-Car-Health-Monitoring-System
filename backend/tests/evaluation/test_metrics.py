"""Hermetic tests for the detection / health / latency metric math.

These run entirely on hand-computed fixtures — no database, broker, LLM or
network. They guard the integrity-critical aggregation from silent regressions.
"""

from __future__ import annotations

import pytest

from evaluation.metrics.detection import (
    classification_report,
    confusion_matrix,
    macro_f1,
    per_label_metrics,
)
from evaluation.metrics.health import rank_auc, roc_auc, score_distribution
from evaluation.metrics.latency import percentile, summarize_latency

LABELS = ["thermal", "electrical", "engine_load", "none"]

PAIRS = [
    ("thermal", "thermal"),
    ("electrical", "thermal"),
    ("engine_load", "engine_load"),
    ("none", "none"),
]


def test_confusion_matrix_counts() -> None:
    matrix = confusion_matrix(PAIRS, LABELS)
    assert matrix["thermal"]["thermal"] == 1
    assert matrix["electrical"]["thermal"] == 1
    assert matrix["engine_load"]["engine_load"] == 1
    assert matrix["none"]["none"] == 1
    assert sum(sum(row.values()) for row in matrix.values()) == 4


def test_per_label_metrics_hand_computed() -> None:
    report = per_label_metrics(PAIRS, LABELS)
    thermal = report["thermal"]
    assert thermal["tp"] == 1
    assert thermal["fp"] == 1
    assert thermal["fn"] == 0
    assert thermal["precision"] == pytest.approx(0.5)
    assert thermal["recall"] == pytest.approx(1.0)
    assert thermal["f1"] == pytest.approx(2 / 3)

    electrical = report["electrical"]
    assert electrical["tp"] == 0
    assert electrical["fn"] == 1
    assert electrical["recall"] == 0.0


def test_classification_report_hand_computed() -> None:
    report = classification_report(PAIRS, LABELS)
    assert report["n_episodes"] == 4
    assert report["accuracy"] == pytest.approx(0.75)
    # macro over labels with support>0 or predictions>0: thermal, electrical,
    # engine_load, none -> (2/3 + 0 + 1 + 1) / 4
    assert report["macro_f1"] == pytest.approx((2 / 3 + 0 + 1 + 1) / 4)
    assert report["weighted_f1"] == pytest.approx((2 / 3 + 0 + 1 + 1) / 4)


def test_macro_f1_ignores_absent_labels() -> None:
    per_label = per_label_metrics([("a", "a")], ["a", "b"])
    assert macro_f1(per_label) == pytest.approx(1.0)


def test_roc_auc_perfect_and_reversed() -> None:
    # Lower score == anomaly.
    assert roc_auc([100, 90, 80, 70], [False, False, True, True]) == pytest.approx(1.0)
    assert roc_auc([70, 80, 90, 100], [False, False, True, True]) == pytest.approx(0.0)


def test_roc_auc_all_ties_is_half() -> None:
    assert roc_auc([80, 80, 80], [True, False, True]) == pytest.approx(0.5)


def test_roc_auc_matches_rank_auc_with_ties() -> None:
    scores = [90, 90, 70, 100, 70]
    positives = [False, True, True, False, True]
    assert roc_auc(scores, positives) == rank_auc(scores, positives)


def test_roc_auc_undefined_for_single_class() -> None:
    assert roc_auc([1, 2, 3], [True, True, True]) is None


def test_score_distribution() -> None:
    dist = score_distribution([100, 80, 60, None])
    assert dist["count"] == 3
    assert dist["min"] == 60
    assert dist["max"] == 100
    assert dist["median"] == 80


def test_percentiles_nearest_rank() -> None:
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(values, 0.0) == 1
    assert percentile(values, 0.5) == 5
    assert percentile(values, 1.0) == 10
    assert summarize_latency(values)["count"] == 10


def test_latency_ignores_none() -> None:
    stats = summarize_latency([1.0, None, 3.0])
    assert stats["count"] == 2
    assert stats["min"] == 1.0
    assert stats["max"] == 3.0
