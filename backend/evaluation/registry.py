"""Pre-registered reference labels and provenance models for the accuracy study.

Everything in this module is part of the *frozen* pre-registration described in
``docs/research/accuracy_evaluation_plan.md`` §4. The label mappings here are the
ground truth for the evaluation and must not be tuned against results. They are
derived from the *injected physical condition* (the simulator scenario the
harness chose), never from anything the analyzer produced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

#: Provenance tag required on every result. See plan §2 / §10.
ProvenanceTag = Literal["MEASURED", "SIMULATED", "MANUALLY_LABELLED", "UNVALIDATED"]

#: Reference fault families (the taxonomy the injected scenarios map onto) plus
#: the "no fault" control label.
FaultFamily = Literal["none", "thermal", "electrical", "engine_load", "engine_speed", "fuel"]

#: Fixed ordering used to break ties when an episode fires findings from more
#: than one family. Highest severity wins first; on a severity tie the earliest
#: entry in this tuple wins. Frozen before the first run.
FAMILY_PRECEDENCE: tuple[FaultFamily, ...] = (
    "thermal",
    "electrical",
    "engine_load",
    "engine_speed",
    "fuel",
    "none",
)

_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}

#: App-side aggregation of deterministic rule ids into reference families. This
#: is a documented *mapping* of analyzer output, not a label of the data.
RULE_FAMILY: dict[str, FaultFamily] = {
    "COOLANT_TEMP_HIGH": "thermal",
    "OIL_TEMP_HIGH": "thermal",
    "RAPID_COOLANT_RISE": "thermal",
    "RAPID_OIL_TEMP_RISE": "thermal",
    "BATTERY_VOLTAGE_LOW": "electrical",
    "BATTERY_VOLTAGE_HIGH": "electrical",
    "ENGINE_LOAD_HIGH": "engine_load",
    "RPM_UNUSUAL": "engine_speed",
    "FUEL_LEVEL_LOW": "fuel",
}

#: Non-alert-worthy findings that describe the data, not the vehicle. Excluded
#: from predicted-family aggregation exactly as ``AlertService`` excludes them.
DATA_QUALITY_RULES: frozenset[str] = frozenset(
    {
        "INSUFFICIENT_DATA",
        "LIMITED_DATA",
        "LIVE_DATA_SUFFICIENCY",
        "TELEMETRY_GAP",
        "LOW_DATA_COVERAGE",
    }
)

#: Injected scenario -> reference family (ground truth).
SCENARIO_FAMILY: dict[str, FaultFamily] = {
    "normal": "none",
    "high_temperature": "thermal",
    "low_battery": "electrical",
    "high_engine_load": "engine_load",
}

#: Injected scenario -> the rule ids a correct detector must produce, and the
#: minimum severity expected. Frozen before the first run.
SCENARIO_EXPECTED_RULES: dict[str, tuple[tuple[str, ...], str]] = {
    # scenario: (expected rule ids, minimum acceptable severity)
    "normal": ((), "info"),
    "high_temperature": (("COOLANT_TEMP_HIGH", "OIL_TEMP_HIGH"), "warning"),
    "low_battery": (("BATTERY_VOLTAGE_LOW",), "warning"),
    "high_engine_load": (("ENGINE_LOAD_HIGH",), "warning"),
}


class ScenarioSpec(BaseModel):
    """One deterministic generator configuration (frozen)."""

    scenario: str
    seed: int
    duration_seconds: float = 180.0
    interval_seconds: float = 1.0
    steady_suffix_seconds: float = 60.0


class EpisodeProvenance(BaseModel):
    """Per-episode provenance record (plan §4.3)."""

    dataset_id: str
    episode_id: str
    scenario: str
    seed: int
    run_id: str
    duration_seconds: float
    interval_seconds: float
    reference_family: FaultFamily
    expected_rule_ids: tuple[str, ...]
    expected_min_severity: str
    reference_source: str = "harness-injected-scenario"
    label_method: str = "injected-physical-condition"
    label_version: str = "1.0"
    provenance: ProvenanceTag = "SIMULATED"
    limitations: tuple[str, ...] = (
        "synthetic telemetry from the in-repo simulator; not real-world validation",
        "reference label is the scenario chosen by the harness, not an independent sensor",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DatasetManifest(BaseModel):
    """Top-level dataset provenance (plan §4.3)."""

    dataset_id: str
    generator: str
    description: str
    reference_source: str
    label_method: str
    label_version: str
    code_revision: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limitations: tuple[str, ...]
    episodes: list[EpisodeProvenance]


def rules_to_family(rule_findings: list[dict]) -> list[FaultFamily]:
    """Map alert-worthy findings to the distinct reference families they imply.

    Only warning/critical, non-data-quality rules participate (mirrors
    ``AlertService.is_alert_worthy``). Returns the families in ``FAMILY_PRECEDENCE``
    order, de-duplicated.
    """
    present: set[FaultFamily] = set()
    for finding in rule_findings:
        severity = finding.get("severity")
        rule_id = finding.get("rule_id")
        if severity not in ("warning", "critical"):
            continue
        if not isinstance(rule_id, str) or rule_id in DATA_QUALITY_RULES:
            continue
        family = RULE_FAMILY.get(rule_id)
        if family is not None:
            present.add(family)
    return [family for family in FAMILY_PRECEDENCE if family in present]


def primary_family(findings: list[dict]) -> FaultFamily:
    """Reduce an episode's findings to one predicted family (plan §4.2).

    Highest severity first; ties broken by ``FAMILY_PRECEDENCE``. An episode with
    no alert-worthy finding predicts ``none``.
    """
    best_family: FaultFamily = "none"
    best_rank = -1
    best_order = len(FAMILY_PRECEDENCE)
    for finding in findings:
        severity = finding.get("severity")
        rule_id = finding.get("rule_id")
        if severity not in ("warning", "critical"):
            continue
        if not isinstance(rule_id, str) or rule_id in DATA_QUALITY_RULES:
            continue
        family = RULE_FAMILY.get(rule_id)
        if family is None:
            continue
        rank = _SEVERITY_RANK.get(str(severity), 0)
        order = FAMILY_PRECEDENCE.index(family)
        if rank > best_rank or (rank == best_rank and order < best_order):
            best_family, best_rank, best_order = family, rank, order
    return best_family


def severity_at_least(severity: str, minimum: str) -> bool:
    return _SEVERITY_RANK.get(severity, -1) >= _SEVERITY_RANK.get(minimum, 0)
