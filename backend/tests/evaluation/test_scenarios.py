"""Hermetic tests for scenario generation, label mapping and analyzer wiring.

No DB/broker/LLM. Verifies that the evaluation reuses the *shipped* engine, that
generation is deterministic, and that the pre-registered label reduction behaves
as documented.
"""

from __future__ import annotations

import pytest

from evaluation.registry import ScenarioSpec, primary_family
from evaluation.runner import analyze_episode
from evaluation.scenarios import generate_episode, steady_suffix


def test_generation_is_deterministic() -> None:
    spec = ScenarioSpec(scenario="high_temperature", seed=1)
    first = generate_episode("a", spec)
    second = generate_episode("b", spec)
    assert [p.values for p in first.points] == [p.values for p in second.points]
    assert len(first.points) == 180


def test_unknown_scenario_rejected() -> None:
    with pytest.raises(ValueError):
        generate_episode("d", ScenarioSpec(scenario="nope", seed=1))


def test_primary_family_severity_then_precedence() -> None:
    both_warning = [
        {"rule_id": "RAPID_COOLANT_RISE", "severity": "warning", "category": "temperature"},
        {"rule_id": "BATTERY_VOLTAGE_LOW", "severity": "warning", "category": "electrical"},
    ]
    assert primary_family(both_warning) == "thermal"

    critical_beats_precedence = [
        {"rule_id": "RAPID_COOLANT_RISE", "severity": "warning", "category": "temperature"},
        {"rule_id": "ENGINE_LOAD_HIGH", "severity": "critical", "category": "engine"},
    ]
    assert primary_family(critical_beats_precedence) == "engine_load"


def test_primary_family_none_when_no_alert_worthy_finding() -> None:
    assert primary_family([]) == "none"
    assert primary_family([{"rule_id": "TELEMETRY_GAP", "severity": "info", "category": "data_quality"}]) == "none"


def test_steady_suffix_is_last_sixty_seconds() -> None:
    spec = ScenarioSpec(scenario="normal", seed=1)
    episode = generate_episode("d", spec)
    suffix = steady_suffix(episode.points, spec)
    span = (suffix[-1].timestamp - suffix[0].timestamp).total_seconds()
    assert span == pytest.approx(59.0)
    assert len(suffix) == 60


def test_high_temperature_flags_coolant_in_steady_view() -> None:
    spec = ScenarioSpec(scenario="high_temperature", seed=1)
    results = {r.view: r for r in analyze_episode(generate_episode("d", spec), spec)}
    steady_rules = {f["rule_id"] for f in results["steady"].findings}
    assert "COOLANT_TEMP_HIGH" in steady_rules
    assert results["steady"].predicted_family == "thermal"


def test_normal_control_clean_steady_dirty_full() -> None:
    spec = ScenarioSpec(scenario="normal", seed=1)
    results = {r.view: r for r in analyze_episode(generate_episode("d", spec), spec)}
    assert results["steady"].predicted_family == "none"
    full_rules = {f["rule_id"] for f in results["full"].findings}
    assert "RAPID_COOLANT_RISE" in full_rules
    assert "RAPID_OIL_TEMP_RISE" in full_rules
