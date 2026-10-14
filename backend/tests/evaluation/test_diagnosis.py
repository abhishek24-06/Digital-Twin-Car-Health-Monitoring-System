"""Hermetic tests for the AI-diagnosis grounding contract (plan §6, RQ5).

These measure only *grounding* — never diagnostic accuracy, which has no
reference labels here.
"""

from __future__ import annotations

import pytest

from evaluation.metrics.diagnosis import citation_resolution, grounding_report

CONTEXT = {
    "statistics": {"coolant_temperature": {}, "engine_load": {}},
    "findings": [
        {"rule_id": "COOLANT_TEMP_HIGH", "metric": "coolant_temperature", "severity": "critical"}
    ],
}

DIAGNOSIS = {
    "diagnosis": {
        "summary": "Coolant temperature is elevated.",
        "evidence": [
            {"rule_id": "COOLANT_TEMP_HIGH", "metric": "coolant_temperature"},
            {"rule_id": "TOTALLY_MADE_UP"},
            {"metric": "engine_load"},
        ],
        "recommended_actions": [{"action": "inspect cooling system", "priority": "high"}],
        "cited_sources": [0, 5],
        "manufacturer_evidence": [{"index": 0}],
    }
}


def test_grounding_rate_counts_matching_evidence() -> None:
    report = grounding_report(DIAGNOSIS, CONTEXT)
    assert report["n_evidence"] == 3
    assert report["n_grounded"] == 2
    assert report["grounding_rate"] == pytest.approx(2 / 3)
    assert report["unresolved_evidence"] == [
        {"rule_id": "TOTALLY_MADE_UP", "metric": None, "reason": "no-matching-evidence"}
    ]
    assert report["has_summary"] is True
    assert report["has_recommended_actions"] is True
    assert "NOT EVALUABLE" in report["status"]


def test_grounding_handles_missing_evidence() -> None:
    report = grounding_report({"diagnosis": {"summary": "x"}}, CONTEXT)
    assert report["n_evidence"] == 0
    assert report["grounding_rate"] is None


def test_citation_resolution_only_counts_retrieved_indices() -> None:
    report = citation_resolution(DIAGNOSIS)
    assert report["n_cited"] == 2
    assert report["n_resolvable"] == 1
    assert report["citation_resolution_rate"] == 0.5


def test_grounding_accepts_flat_diagnosis_shape() -> None:
    flat = {"evidence": [{"rule_id": "COOLANT_TEMP_HIGH"}]}
    assert grounding_report(flat, CONTEXT)["grounding_rate"] == 1.0
