"""Detection / classification metrics (plan §6, RQ1).

Pure functions over ``(reference, predicted)`` label pairs. No I/O, no DB, no
knowledge of the analyzer internals — easy to test against hand-computed values.
"""

from __future__ import annotations

from collections.abc import Sequence

LabelPair = tuple[str, str]
LabelList = Sequence[str]


def confusion_matrix(pairs: list[tuple[str, str]], labels: list[str]) -> dict[str, dict[str, int]]:
    """Reference (row) x predicted (column) counts over ``labels``."""
    matrix = {label: dict.fromkeys(labels, 0) for label in labels}
    for true, pred in pairs:
        if true not in matrix:
            raise ValueError(f"unknown reference label {true!r}")
        if pred not in matrix[true]:
            raise ValueError(f"unknown predicted label {pred!r}")
        matrix[true][pred] += 1
    return matrix


def per_label_metrics(pairs: list[tuple[str, str]], labels: list[str]) -> dict[str, dict[str, float]]:
    """Per-label TP/FP/FN/TN and precision/recall/F1 (one-vs-rest)."""
    report: dict[str, dict[str, float]] = {}
    for label in labels:
        tp = fp = fn = tn = 0
        for true, pred in pairs:
            if true == label and pred == label:
                tp += 1
            elif pred == label:
                fp += 1
            elif true == label:
                fn += 1
            else:
                tn += 1
        precision = _div(tp, tp + fp)
        recall = _div(tp, tp + fn)
        f1 = _div(2 * precision * recall, precision + recall)
        report[label] = {
            "tp": float(tp),
            "fp": float(fp),
            "fn": float(fn),
            "tn": float(tn),
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": float(tp + fn),
            "predicted": float(tp + fp),
        }
    return report


def macro_f1(per_label: dict[str, dict[str, float]]) -> float | None:
    """Mean F1 over labels that occur as a reference or a prediction."""
    active = [m["f1"] for m in per_label.values() if m["support"] > 0 or m["predicted"] > 0]
    return round(sum(active) / len(active), 6) if active else None


def weighted_f1(per_label: dict[str, dict[str, float]]) -> float | None:
    """Support-weighted mean F1 over labels with reference support."""
    weighted = [(m["support"], m["f1"]) for m in per_label.values() if m["support"] > 0]
    total = sum(count for count, _ in weighted)
    return round(sum(count * f1 for count, f1 in weighted) / total, 6) if total else None


def classification_report(pairs: list[tuple[str, str]], labels: list[str]) -> dict[str, object]:
    """Full RQ1 report: confusion matrix, per-label table, accuracy, macro/weighted F1."""
    per_label = per_label_metrics(pairs, labels)
    accuracy = _div(sum(1 for true, pred in pairs if true == pred), len(pairs)) if pairs else None
    return {
        "n_episodes": len(pairs),
        "labels": list(labels),
        "confusion_matrix": confusion_matrix(pairs, labels),
        "per_label": per_label,
        "accuracy": round(accuracy, 6) if accuracy is not None else None,
        "macro_f1": macro_f1(per_label),
        "weighted_f1": weighted_f1(per_label),
    }


def _div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


__all__ = [
    "classification_report",
    "confusion_matrix",
    "macro_f1",
    "per_label_metrics",
    "weighted_f1",
]
