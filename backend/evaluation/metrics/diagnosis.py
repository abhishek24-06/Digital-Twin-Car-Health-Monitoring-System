"""AI-diagnosis *grounding* metrics (plan §6, RQ5).

RQ5 **correctness** (top-1/top-k diagnosis accuracy, fault-category P/R/F1) is
NOT EVALUABLE here: no expert-labelled reference diagnoses exist. This module
only measures the *grounding contract* of a ``DiagnosisResponse`` against a
``HealthContext`` — i.e. whether the diagnosis's claims trace to real evidence in
the context. These are system-contract measures and must never be reported as
diagnostic accuracy.
"""

from __future__ import annotations

from typing import Any

RQ5_STATUS = (
    "NOT EVALUABLE for correctness: no expert-labelled reference diagnoses exist. "
    "Grounding-contract metrics below are not diagnostic accuracy."
)


def _diagnosis_content(diagnosis: dict[str, Any]) -> dict[str, Any]:
    inner = diagnosis.get("diagnosis")
    return inner if isinstance(inner, dict) else diagnosis


def grounding_report(diagnosis: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Measure how much of a diagnosis resolves to the supplied health context.

    ``context`` is a ``HealthContext``-shaped dict (``rule_id`` + ``metric`` are
    read from ``findings``). An evidence item is *grounded* when its ``rule_id``
    matches a real finding rule id, or its ``metric`` matches a supported metric
    present in the context statistics.
    """
    content = _diagnosis_content(diagnosis)
    evidence = content.get("evidence") or []

    findings = context.get("findings") or []
    rule_ids = {
        str(f.get("rule_id")) for f in findings if isinstance(f, dict) and f.get("rule_id")
    }
    metrics = set((context.get("statistics") or {}).keys())
    metrics.update(str(f.get("metric")) for f in findings if isinstance(f, dict) and f.get("metric"))

    grounded = 0
    unresolved: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            unresolved.append({"item": item, "reason": "not-an-object"})
            continue
        rule_id = item.get("rule_id")
        metric = item.get("metric")
        if (rule_id and str(rule_id) in rule_ids) or (metric and str(metric) in metrics):
            grounded += 1
        else:
            unresolved.append({"rule_id": rule_id, "metric": metric, "reason": "no-matching-evidence"})

    total = len(evidence)
    return {
        "status": RQ5_STATUS,
        "n_evidence": total,
        "n_grounded": grounded,
        "grounding_rate": round(grounded / total, 6) if total else None,
        "unresolved_evidence": unresolved,
        "has_summary": bool(str(content.get("summary") or "").strip()),
        "has_recommended_actions": bool(content.get("recommended_actions")),
    }


def citation_resolution(diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Whether ``cited_sources`` indices resolve to retrieved manufacturer evidence."""
    content = _diagnosis_content(diagnosis)
    cited = content.get("cited_sources") or []
    retrieved = content.get("manufacturer_evidence") or []
    valid_indices = {
        int(item.get("index"))
        for item in retrieved
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }
    resolvable = [int(c) for c in cited if isinstance(c, int) and int(c) in valid_indices]
    return {
        "n_cited": len(cited),
        "n_resolvable": len(resolvable),
        "citation_resolution_rate": round(len(resolvable) / len(cited), 6) if cited else None,
    }


__all__ = ["RQ5_STATUS", "citation_resolution", "grounding_report"]
