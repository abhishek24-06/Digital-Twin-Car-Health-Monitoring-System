"""Health-assessment metrics (plan §6, RQ2).

RQ2 has **no independent continuous health reference**, so no regression metrics
(MAE/RMSE/R2) are defined or computed here. The only defensible measurement is
ordinal *discrimination* of the injected condition, plus a descriptive status
confusion that is explicitly flagged as partly circular (the status buckets and
the rules share thresholds).
"""

from __future__ import annotations

from collections.abc import Sequence


def roc_auc(scores: Sequence[float | None], positives: Sequence[bool]) -> float | None:
    """AUC of the anomaly indicator using the health score as a ranker.

    ``positives[i] is True`` marks a reference **anomaly**. A lower health score
    should indicate an anomaly, so a pair (anomaly ``a``, normal ``n``) is
    concordant when ``score[a] < score[n]``; ties contribute 0.5. A perfect
    detector scores 1.0; chance is 0.5. Returns ``None`` if either class is empty.

    Implemented by direct concordance counting because the episode counts here are
    small (tens), and an obviously-correct implementation is preferable.
    """
    cleaned = [(float(s), bool(p)) for s, p in zip(scores, positives, strict=True) if s is not None]
    pos = [s for s, p in cleaned if p]
    neg = [s for s, p in cleaned if not p]
    if not pos or not neg:
        return None
    concordant = 0.0
    for s_pos in pos:
        for s_neg in neg:
            if s_pos < s_neg:
                concordant += 1.0
            elif s_pos == s_neg:
                concordant += 0.5
    return round(concordant / (len(pos) * len(neg)), 6)


def rank_auc(scores: Sequence[float | None], positives: Sequence[bool]) -> float | None:
    """Average-rank AUC; must equal :func:`roc_auc` (used as a cross-check)."""
    cleaned = [(float(s), bool(p)) for s, p in zip(scores, positives, strict=True) if s is not None]
    n_pos = sum(1 for _, p in cleaned if p)
    n_neg = len(cleaned) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    # Rank descending on the health score so rank 1 == highest (healthiest) score.
    # Anomalies have the *lowest* scores, so they carry the highest ranks, and the
    # standard Mann-Whitney U then equals P(score_anomaly < score_normal).
    order = sorted(range(len(cleaned)), key=lambda i: -cleaned[i][0])
    ranks = [0.0] * len(cleaned)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and cleaned[order[j + 1]][0] == cleaned[order[i]][0]:
            j += 1
        average_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    rank_sum_pos = sum(ranks[i] for i, (_, p) in enumerate(cleaned) if p)
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2.0
    return round(u / (n_pos * n_neg), 6)


def status_confusion(
    true_labels: Sequence[str], predicted_status: Sequence[str]
) -> dict[str, dict[str, int]]:
    """Descriptive confusion of injected family vs. produced health_status.

    Partly circular: ``health_status`` buckets and the deterministic rules share
    thresholds, so this is reported as description, never as accuracy.
    """
    matrix: dict[str, dict[str, int]] = {}
    for true, pred in zip(true_labels, predicted_status, strict=True):
        row = matrix.setdefault(true, {})
        row[pred] = row.get(pred, 0) + 1
    return matrix


def score_distribution(scores: Sequence[float | None]) -> dict[str, float | None]:
    values = sorted(float(s) for s in scores if s is not None)
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None, "mean": None}
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0
    return {
        "count": len(values),
        "min": values[0],
        "median": median,
        "max": values[-1],
        "mean": round(sum(values) / len(values), 4),
    }


__all__ = ["rank_auc", "roc_auc", "score_distribution", "status_confusion"]
