"""Hermetic tests for the pipeline evaluation (plan §5.1, §6, §10).

These never touch a database or broker: they pin the pre-registered alert
arithmetic, the report's single-source contract and the fail-closed isolation
guard. The integration harness is covered separately (and only when
``DT_EVAL_DATABASE_URL`` points at the disposable test database).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from evaluation.pipeline import metrics as M
from evaluation.pipeline.figures import render_figures
from evaluation.pipeline.harness import IsolationError, resolve_database_url
from evaluation.pipeline.report import render_markdown

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _alert(
    alert_id: str,
    rule_id: str,
    severity: str,
    *,
    offset_seconds: int,
    resolved_offset: int | None = None,
    occurrence_count: int = 1,
    provisional: bool = False,
) -> M.AlertObservation:
    first = T0 + timedelta(seconds=offset_seconds)
    return M.AlertObservation(
        alert_id=alert_id,
        rule_id=rule_id,
        severity=severity,
        status="resolved" if resolved_offset is not None else "open",
        first_seen_at=first,
        last_seen_at=first,
        resolved_at=(T0 + timedelta(seconds=resolved_offset) if resolved_offset is not None else None),
        occurrence_count=occurrence_count,
        simulation_run_id="run",
        provisional_at_create=provisional,
    )


def _episode(
    episode_id: str,
    expected: tuple[str, ...],
    min_severity: str,
    alerts: list[M.AlertObservation],
    *,
    family: str = "thermal",
    duration: float = 180.0,
) -> M.EpisodeObservation:
    return M.EpisodeObservation(
        episode_id=episode_id,
        scenario="high_temperature" if expected else "normal",
        seed=1,
        run_id="run",
        onset=T0,
        end=T0 + timedelta(seconds=duration),
        duration_seconds=duration,
        reference_family=family,
        expected_rule_ids=expected,
        expected_min_severity=min_severity,
        alerts=alerts,
        monitor_passes=int(duration),
        failed_passes=0,
        snapshots_persisted=int(duration),
    )


def test_alert_match_requires_expected_rule_and_window() -> None:
    episode = _episode(
        "A", ("COOLANT_TEMP_HIGH",), "warning", []
    )
    inside = _alert("a", "COOLANT_TEMP_HIGH", "critical", offset_seconds=5)
    after = _alert("b", "COOLANT_TEMP_HIGH", "critical", offset_seconds=999)
    wrong_rule = _alert("c", "RAPID_COOLANT_RISE", "warning", offset_seconds=5)

    assert M.alert_matches_episode(inside, episode)
    assert not M.alert_matches_episode(after, episode)
    assert not M.alert_matches_episode(wrong_rule, episode)


def test_summarize_alerts_precision_recall_and_false_alarms() -> None:
    episodes = [
        _episode(
            "fault-A",
            ("COOLANT_TEMP_HIGH",),
            "warning",
            [
                _alert("a1", "COOLANT_TEMP_HIGH", "critical", offset_seconds=5),
                _alert("a2", "RAPID_COOLANT_RISE", "warning", offset_seconds=3),
            ],
        ),
        _episode(
            "control-B",
            (),
            "warning",
            [_alert("b1", "RAPID_COOLANT_RISE", "warning", offset_seconds=2)],
            family="none",
        ),
        _episode(
            "fault-C",
            ("BATTERY_VOLTAGE_LOW",),
            "warning",
            [],
            family="electrical",
        ),
    ]
    summary = M.summarize_alerts(episodes)

    assert summary["episodes"] == 3
    assert summary["positive_episodes"] == 2
    assert summary["episodes_detected"] == 1
    assert summary["episodes_missed"] == 1
    assert summary["episode_recall"] == pytest.approx(0.5)
    assert summary["episode_precision"] == pytest.approx(0.5)
    assert summary["alerts_total"] == 3
    assert summary["alerts_matching"] == 1
    assert summary["alerts_false_positive"] == 2
    assert summary["alert_precision"] == pytest.approx(1 / 3)
    assert summary["expected_rule_pairs"] == 2
    assert summary["expected_rule_pairs_hit"] == 1
    assert summary["expected_rule_recall"] == pytest.approx(0.5)
    # 3 episodes x 180 s = 0.15 vehicle-hours; 2 false alarms.
    assert summary["exposure_hours"] == pytest.approx(0.15)
    assert summary["false_alarms_per_vehicle_hour"] == pytest.approx(2 / 0.15)
    assert summary["duplicate_alert_rows"] == 0
    assert summary["time_to_first_detection_n"] == 1
    assert summary["time_to_first_detection_seconds"]["min"] == pytest.approx(5.0)
    assert "fault-C" in summary["missed_episode_ids"]


def test_duplicate_alert_rows_are_counted_per_episode_and_rule() -> None:
    episode = _episode(
        "A",
        ("COOLANT_TEMP_HIGH",),
        "warning",
        [
            _alert("a1", "COOLANT_TEMP_HIGH", "critical", offset_seconds=5),
            _alert("a2", "COOLANT_TEMP_HIGH", "critical", offset_seconds=6),
        ],
    )
    summary = M.summarize_alerts([episode])
    assert summary["duplicate_alert_rows"] == 1
    assert summary["duplicate_alert_rows_by_episode"] == {"A": 1}


def test_time_to_resolution_uses_recovery_onset() -> None:
    episode = _episode(
        "A",
        ("BATTERY_VOLTAGE_LOW",),
        "warning",
        [
            _alert(
                "a1",
                "BATTERY_VOLTAGE_LOW",
                "warning",
                offset_seconds=5,
                resolved_offset=100,
            )
        ],
    )
    episode.recovery_onset = T0 + timedelta(seconds=50)
    summary = M.summarize_alerts([episode])
    assert summary["time_to_resolution_n"] == 1
    assert summary["time_to_resolution_seconds"]["min"] == pytest.approx(50.0)


def test_report_renders_from_metrics_only() -> None:
    metrics = {
        "meta": {
            "status": "EXECUTED",
            "dataset_id": "synthetic-pipeline-v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "provenance": "SIMULATED + MEASURED",
            "code_revision": "abc",
            "commands": ["python -m evaluation.pipeline all"],
        },
        "alerts": {
            "summary": {
                "episodes": 12,
                "positive_episodes": 9,
                "exposure_hours": 0.6,
                "episodes_detected": 9,
                "episode_recall": 1.0,
                "episode_precision": 0.75,
                "alerts_total": 12,
                "alerts_matching": 9,
                "alerts_false_positive": 3,
                "alert_precision": 0.75,
                "expected_rule_pairs": 12,
                "expected_rule_pairs_hit": 9,
                "expected_rule_recall": 0.75,
                "false_alarms_per_vehicle_hour": 5.0,
                "duplicate_alert_rows": 0,
                "recurrence_updates_total": 40,
                "alerts_provisional_at_create": 4,
                "alerts_definitive_at_create": 8,
                "time_to_first_detection_seconds": {
                    "count": 9,
                    "min": 2.0,
                    "p50": 3.0,
                    "p95": None,
                    "p95_justified": False,
                    "p99": None,
                    "p99_justified": False,
                    "max": 5.0,
                    "mean": 3.1,
                },
                "unresolved_alerts": 12,
                "per_episode": [],
            },
            "scope_counts": {"current_session": 2160},
            "recovery": {"summary": {}, "cases": []},
        },
        "latency": {
            "n_samples": 180,
            "n_alerts": 6,
            "ingest_ms": {"count": 180, "min": 1.0, "p50": 2.0, "p95": 3.0,
                          "p95_justified": True, "p99": 4.0, "p99_justified": True,
                          "max": 5.0, "mean": 2.2},
            "monitor_pass_ms": {"count": 180, "min": 0.5, "p50": 1.0, "p95": 1.5,
                                "p95_justified": True, "p99": None, "p99_justified": False,
                                "max": 2.0, "mean": 1.1},
            "engine_analysis_duration_ms": {"count": 180, "min": 0.1, "p50": 0.2,
                                            "p95": None, "p95_justified": True,
                                            "p99": None, "p99_justified": False,
                                            "max": 0.4, "mean": 0.2},
            "publish_to_alert_ms": {"count": 6, "min": 4.0, "p50": 6.0, "p95": None,
                                    "p95_justified": False, "p99": None,
                                    "p99_justified": False, "max": 9.0, "mean": 6.3},
            "failures": [],
        },
        "robustness": {
            "cases": [
                {
                    "case": "clean_baseline",
                    "description": "5 samples",
                    "persisted": 5,
                    "expected_range": [5, 5],
                    "passed": True,
                    "detail": "ok",
                }
            ]
        },
    }
    report = render_markdown(metrics)
    assert "EXECUTED" in report
    assert "Episode recall: 100.0%" in report
    assert "p95=n/a (not justified: n<20)" in report
    assert "current_session" in report
    assert "clean_baseline" in report


def test_report_marks_not_executed_without_measurements() -> None:
    report = render_markdown(
        {
            "meta": {
                "status": "NOT EXECUTED",
                "blocker": "mosquitto executable not found",
                "dataset_id": "synthetic-pipeline-v1",
                "generated_at": "2026",
                "provenance": "NOT EXECUTED",
                "code_revision": "abc",
            }
        }
    )
    assert "NOT EXECUTED" in report
    assert "mosquitto executable not found" in report


def test_figures_render_self_contained_svg_for_present_sections() -> None:
    metrics = {
        "alerts": {
            "summary": {
                "per_episode": [
                    {
                        "episode_id": "high_temperature-seed1",
                        "matching_alerts": ["COOLANT_TEMP_HIGH"],
                        "false_positive_alerts": [],
                    },
                    {
                        "episode_id": "normal-seed1",
                        "matching_alerts": [],
                        "false_positive_alerts": ["RAPID_COOLANT_RISE"],
                    },
                ]
            },
            "recovery": {
                "cases": [
                    {
                        "scenario": "low_battery",
                        "expected_rule_ids": ["BATTERY_VOLTAGE_LOW"],
                        "resolved_rule_ids": ["BATTERY_VOLTAGE_LOW"],
                        "ttr_seconds": 30.0,
                    }
                ]
            },
        },
        "latency": {
            "samples": [{"monitor_pass_ms": value} for value in (10.0, 12.0, 40.0)],
            "monitor_pass_ms": {"p50": 12.0, "p95": 40.0},
        },
        "robustness": {
            "cases": [
                {"case": "clean_baseline", "persisted": 5, "expected_range": [5, 5]},
            ]
        },
    }
    figures = render_figures(metrics)
    assert set(figures) == {
        "alert-quality.svg",
        "recovery-ttr.svg",
        "latency-monitor-pass.svg",
        "robustness-persisted.svg",
    }
    for svg in figures.values():
        assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_figures_render_nothing_when_sections_absent() -> None:
    assert render_figures({"meta": {"status": "NOT EXECUTED"}}) == {}


def test_report_renders_clock_semantics_when_present() -> None:
    report = render_markdown(
        {
            "meta": {"status": "EXECUTED", "dataset_id": "synthetic-pipeline-v1"},
            "environment": {
                "clock_semantics": {"rq4_latency": "wall-clock monotonic host-local"},
            },
        }
    )
    assert "Clock semantics:" in report
    assert "rq4_latency" in report
    assert "wall-clock monotonic host-local" in report


def test_isolation_guard_accepts_only_loopback_disposable_database(monkeypatch) -> None:
    monkeypatch.delenv("DT_EVAL_DATABASE_URL", raising=False)
    good = "postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_eval_test"
    assert resolve_database_url(good) == good
    with pytest.raises(IsolationError):
        resolve_database_url("postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin")
    with pytest.raises(IsolationError):
        resolve_database_url("postgresql+asyncpg://u:p@db.example.com:5432/digital_twin_eval_test")
    with pytest.raises(IsolationError):
        resolve_database_url(None)
