from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.intelligence.models import AnalysisWindow, DataQuality, Finding, MetricStatistics
from app.intelligence.scoring import (
    compute_confidence,
    health_status_from_score,
    insufficient_score,
    score_findings,
)


def _finding(severity: str, category: str = "temperature") -> Finding:
    return Finding(rule_id="TEST", severity=severity, category=category, message="test")


def _window() -> AnalysisWindow:
    end = datetime.now(UTC)
    return AnalysisWindow(start=end - timedelta(minutes=1), end=end, window_minutes=1.0)


def _dq(
    total_expected: int = 60,
    sample_count: int = 60,
    *,
    duration_seconds: float = 60.0,
) -> DataQuality:
    return DataQuality(
        sample_count=sample_count,
        expected_sample_count=total_expected,
        coverage_ratio=min(1.0, sample_count / total_expected),
        duration_seconds=duration_seconds,
        max_gap_seconds=1.0,
    )


def test_score_no_findings_is_100_healthy() -> None:
    details = score_findings([])
    assert details.score == 100.0
    assert details.status == "healthy"
    assert details.total_penalty == 0.0
    assert details.components == []


def test_single_warning_scores_90_healthy() -> None:
    details = score_findings([_finding("warning")])
    assert details.score == 90.0
    assert details.status == "healthy"
    assert details.total_penalty == 10.0


def test_single_critical_scores_70_attention() -> None:
    details = score_findings([_finding("critical")])
    assert details.score == 70.0
    assert details.status == "attention"
    assert details.total_penalty == 30.0


def test_info_findings_do_not_penalise_score() -> None:
    details = score_findings([_finding("info", category="data_quality")])
    assert details.score == 100.0
    assert details.status == "healthy"
    assert details.total_penalty == 0.0


def test_multiple_critical_in_same_category_are_capped() -> None:
    findings = [_finding("critical") for _ in range(5)]
    details = score_findings(findings)
    assert details.total_penalty == 40.0
    assert details.score == 60.0
    assert details.status == "attention"
    assert details.components[0].capped is True
    assert details.components[0].penalty == 40.0


def test_score_never_drops_below_zero() -> None:
    findings = [_finding("critical", category=f"cat_{i}") for i in range(8)]
    details = score_findings(findings)
    assert details.score == 0.0
    assert details.status == "critical"


def test_penalty_components_report_severity_and_count() -> None:
    findings = [
        _finding("critical", category="engine"),
        _finding("warning", category="engine"),
        _finding("info", category="data_quality"),
    ]
    details = score_findings(findings)
    by_category = {c.category: c for c in details.components}
    assert by_category["engine"].severity == "critical"
    assert by_category["engine"].finding_count == 2
    assert by_category["engine"].penalty == 40.0  # capped (30 + 10)
    assert by_category["data_quality"].severity == "info"
    assert by_category["data_quality"].penalty == 0.0


def test_health_status_boundaries() -> None:
    assert health_status_from_score(100.0) == "healthy"
    assert health_status_from_score(80.0) == "healthy"
    assert health_status_from_score(79.99) == "attention"
    assert health_status_from_score(60.0) == "attention"
    assert health_status_from_score(59.99) == "critical"
    assert health_status_from_score(0.0) == "critical"
    assert health_status_from_score(None) == "unknown"


def test_confidence_full_data_is_one() -> None:
    window = _window()
    dq = _dq(duration_seconds=window.duration_seconds)
    statistics = {
        f"metric_{i}": MetricStatistics(metric=f"metric_{i}", unit="", count=60) for i in range(11)
    }
    assert compute_confidence(dq, statistics, window) == 1.0


def test_confidence_adapts_to_poor_data() -> None:
    window = _window()
    dq = _dq(total_expected=60, sample_count=10, duration_seconds=10.0)
    confidence = compute_confidence(dq, {}, window)
    assert confidence < 1.0
    assert confidence >= 0.10
    assert confidence == round(confidence, 4)


def test_confidence_lower_bound_never_zero() -> None:
    window = _window()
    dq = _dq(total_expected=60, sample_count=0, duration_seconds=0.0)
    assert compute_confidence(dq, {}, window) == 0.10


def test_insufficient_score_reports_unknown() -> None:
    details = insufficient_score(notes=["sample_count (3) is below minimum"])
    assert details.score is None
    assert details.status == "unknown"
    assert details.notes == ["sample_count (3) is below minimum"]
    assert details.components == []
