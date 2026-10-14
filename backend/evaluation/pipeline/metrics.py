"""Pure alert-quality aggregation for RQ3 (plan §5.1, §6).

Everything here is a pure function over observation records produced by the
isolated-DB harness. Keeping the arithmetic out of the harness means it can be
tested on hand-computed fixtures with no database, broker or network.

Pre-registered matching (frozen in the plan, **not** tunable here):

* an alert matches an episode iff ``alert.rule_id ∈ expected_rule_ids`` **and**
  ``alert.first_seen_at ∈ [onset - W, end + W]`` with ``W = 0 s`` for the
  deterministic snapshot-fed harness;
* a positive episode is *detected* iff a matching alert at severity ≥ the
  episode's expected severity was created inside the window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from evaluation.metrics.latency import summarize_latency
from evaluation.registry import severity_at_least

#: Pre-registered match tolerance (plan §5.1). Frozen at zero seconds.
MATCH_TOLERANCE_SECONDS = 0.0


@dataclass
class AlertObservation:
    """One persisted ``Alert`` row plus harness-captured creation context."""

    alert_id: str
    rule_id: str
    severity: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    occurrence_count: int
    simulation_run_id: str | None
    provisional_at_create: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "status": self.status,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "occurrence_count": self.occurrence_count,
            "simulation_run_id": self.simulation_run_id,
            "provisional_at_create": self.provisional_at_create,
        }


@dataclass
class EpisodeObservation:
    """One fault episode replayed through the live monitor path."""

    episode_id: str
    scenario: str
    seed: int
    run_id: str
    onset: datetime
    end: datetime
    duration_seconds: float
    reference_family: str
    expected_rule_ids: tuple[str, ...]
    expected_min_severity: str
    alerts: list[AlertObservation] = field(default_factory=list)
    monitor_passes: int = 0
    failed_passes: int = 0
    snapshots_persisted: int = 0
    #: Set for recovery experiments: the onset of the verifying clean session.
    recovery_onset: datetime | None = None
    recovery_note: str | None = None

    @property
    def exposure_hours(self) -> float:
        return max(0.0, self.duration_seconds) / 3600.0

    def matching_alerts(self) -> list[AlertObservation]:
        return [a for a in self.alerts if alert_matches_episode(a, self)]

    def detected(self) -> bool:
        return any(
            alert_matches_episode(a, self)
            and severity_at_least(a.severity, self.expected_min_severity)
            for a in self.alerts
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "scenario": self.scenario,
            "seed": self.seed,
            "run_id": self.run_id,
            "onset": self.onset.isoformat(),
            "end": self.end.isoformat(),
            "duration_seconds": self.duration_seconds,
            "reference_family": self.reference_family,
            "expected_rule_ids": list(self.expected_rule_ids),
            "expected_min_severity": self.expected_min_severity,
            "monitor_passes": self.monitor_passes,
            "failed_passes": self.failed_passes,
            "snapshots_persisted": self.snapshots_persisted,
            "recovery_onset": self.recovery_onset.isoformat() if self.recovery_onset else None,
            "alerts": [a.to_dict() for a in self.alerts],
        }


def alert_matches_episode(
    alert: AlertObservation,
    episode: EpisodeObservation,
    *,
    tolerance_seconds: float = MATCH_TOLERANCE_SECONDS,
) -> bool:
    """Pre-registered match rule (plan §5.1). Rule membership + creation time."""
    if alert.rule_id not in episode.expected_rule_ids:
        return False
    lower = episode.onset - timedelta(seconds=tolerance_seconds)
    upper = episode.end + timedelta(seconds=tolerance_seconds)
    return lower <= alert.first_seen_at <= upper


def _seconds(values: list[float]) -> dict[str, float | int | bool | None]:
    return summarize_latency(values)


def summarize_alerts(episodes: list[EpisodeObservation]) -> dict[str, Any]:
    """Compute the pre-registered RQ3 alert metrics over all episodes."""
    positive = [e for e in episodes if e.expected_rule_ids]
    detected = [e for e in positive if e.detected()]
    missed = [e for e in positive if not e.detected()]
    predicted_positive = [e for e in episodes if e.alerts]
    false_positive_episodes = [e for e in predicted_positive if not e.detected()]

    all_alerts = [(e, a) for e in episodes for a in e.alerts]
    # An alert is a false positive when it does not match the episode that
    # produced it (wrong rule, or outside the window).
    matching = [(e, a) for e, a in all_alerts if alert_matches_episode(a, e)]
    false_positives = [(e, a) for e, a in all_alerts if not alert_matches_episode(a, e)]

    # Expected-rule coverage: how many (episode, expected-rule) pairs produced a
    # matching alert of sufficient severity.
    expected_pairs = 0
    expected_pairs_hit = 0
    for episode in positive:
        for rule_id in episode.expected_rule_ids:
            expected_pairs += 1
            if any(
                a.rule_id == rule_id and severity_at_least(a.severity, episode.expected_min_severity)
                for a in episode.alerts
            ):
                expected_pairs_hit += 1

    exposure_hours = sum(e.exposure_hours for e in episodes)
    total_alerts = len(all_alerts)

    # Duplicate rows: more than one persisted Alert row for the same
    # (episode, rule). Dedup should make this zero within a single session.
    duplicate_by_episode: dict[str, int] = {}
    for episode in episodes:
        counts: dict[str, int] = {}
        for alert in episode.alerts:
            counts[alert.rule_id] = counts.get(alert.rule_id, 0) + 1
        extra = sum(count - 1 for count in counts.values() if count > 1)
        if extra:
            duplicate_by_episode[episode.episode_id] = extra
    duplicate_total = sum(duplicate_by_episode.values())

    recurrence_updates = sum(max(0, a.occurrence_count - 1) for _e, a in all_alerts)

    normal_false_positives = [a for e, a in false_positives if e.expected_rule_ids == ()]

    by_family: dict[str, dict[str, int]] = {}
    for episode in episodes:
        bucket = by_family.setdefault(
            episode.reference_family,
            {"episodes": 0, "detected": 0, "alerts": 0, "false_positive_alerts": 0},
        )
        bucket["episodes"] += 1
        bucket["detected"] += 1 if episode.detected() else 0
        bucket["alerts"] += len(episode.alerts)
        bucket["false_positive_alerts"] += sum(
            1 for a in episode.alerts if not alert_matches_episode(a, episode)
        )

    # Time-to-resolution for verified recovery experiments.
    resolution_seconds: list[float] = []
    for episode in episodes:
        if episode.recovery_onset is None:
            continue
        for alert in episode.alerts:
            if alert.resolved_at is None:
                continue
            if alert.rule_id not in episode.expected_rule_ids:
                continue
            resolution_seconds.append(
                (alert.resolved_at - episode.recovery_onset).total_seconds()
            )

    incomplete = [
        e.episode_id
        for e in episodes
        if e.monitor_passes == 0 or e.failed_passes > 0 or _expected_passes(e) > e.monitor_passes
    ]

    return {
        "episodes": len(episodes),
        "positive_episodes": len(positive),
        "exposure_hours": round(exposure_hours, 6),
        "episodes_detected": len(detected),
        "episodes_missed": len(missed),
        "episode_recall": _ratio(len(detected), len(positive)),
        "episode_precision": _ratio(len(detected), len(predicted_positive)),
        "detected_episode_ids": [e.episode_id for e in detected],
        "missed_episode_ids": [e.episode_id for e in missed],
        "false_positive_episode_ids": [e.episode_id for e in false_positive_episodes],
        "alerts_total": total_alerts,
        "alerts_matching": len(matching),
        "alerts_false_positive": len(false_positives),
        "alert_precision": _ratio(len(matching), total_alerts),
        "expected_rule_pairs": expected_pairs,
        "expected_rule_pairs_hit": expected_pairs_hit,
        "expected_rule_recall": _ratio(expected_pairs_hit, expected_pairs),
        "false_alarms_per_vehicle_hour": (
            round(len(false_positives) / exposure_hours, 6) if exposure_hours > 0 else None
        ),
        "duplicate_alert_rows": duplicate_total,
        "duplicate_alert_rows_by_episode": duplicate_by_episode,
        "recurrence_updates_total": recurrence_updates,
        "time_to_first_detection_seconds": _seconds(
            [float(v) for v in _first_detection_deltas(detected)]
        ),
        "time_to_first_detection_n": len(detected),
        "time_to_resolution_seconds": _seconds(resolution_seconds),
        "time_to_resolution_n": len(resolution_seconds),
        "unresolved_alerts": len([a for _, a in all_alerts if a.resolved_at is None]),
        "resolved_alerts": len([a for _, a in all_alerts if a.resolved_at is not None]),
        "alerts_provisional_at_create": sum(1 for _, a in all_alerts if a.provisional_at_create),
        "alerts_definitive_at_create": sum(
            1 for _, a in all_alerts if not a.provisional_at_create
        ),
        "cold_start_false_positive_alerts": len(normal_false_positives),
        "by_reference_family": by_family,
        "incomplete_episode_ids": incomplete,
        "per_episode": [_episode_summary(e) for e in episodes],
    }


def recurrence_seconds(count: int) -> int:
    """Alias kept explicit so the count is never mistaken for seconds."""
    return int(count)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _first_detection_deltas(detected: list[EpisodeObservation]) -> list[float]:
    deltas: list[float] = []
    for episode in detected:
        times = [
            a.first_seen_at
            for a in episode.alerts
            if alert_matches_episode(a, episode)
            and severity_at_least(a.severity, episode.expected_min_severity)
        ]
        if times:
            deltas.append((min(times) - episode.onset).total_seconds())
    return deltas


def _expected_passes(episode: EpisodeObservation) -> int:
    if episode.duration_seconds <= 0:
        return 0
    return int(round(episode.duration_seconds))


def _episode_summary(episode: EpisodeObservation) -> dict[str, Any]:
    return {
        "episode_id": episode.episode_id,
        "scenario": episode.scenario,
        "seed": episode.seed,
        "reference_family": episode.reference_family,
        "expected_rule_ids": list(episode.expected_rule_ids),
        "detected": episode.detected(),
        "alerts": [a.rule_id for a in episode.alerts],
        "matching_alerts": [a.rule_id for a in episode.matching_alerts()],
        "false_positive_alerts": [
            a.rule_id for a in episode.alerts if not alert_matches_episode(a, episode)
        ],
        "monitor_passes": episode.monitor_passes,
        "failed_passes": episode.failed_passes,
        "snapshots_persisted": episode.snapshots_persisted,
    }


__all__ = [
    "MATCH_TOLERANCE_SECONDS",
    "AlertObservation",
    "EpisodeObservation",
    "alert_matches_episode",
    "summarize_alerts",
]
