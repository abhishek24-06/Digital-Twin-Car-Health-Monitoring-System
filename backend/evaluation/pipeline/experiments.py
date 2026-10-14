"""Real-path experiment drivers for RQ3 (alerts), RQ4 (latency) and RQ6 (robustness).

RQ3 replays a deterministic synthetic episode through the **exact two calls the
background monitor makes per vehicle** — ``VehicleHealthService.analyze_live_vehicle``
then ``AlertService.sync_from_snapshot`` — once per sample, on the episode's own
(synthetic, deterministic) clock. This exercises the real snapshot/alert/
deduplication/auto-resolution code paths without depending on wall-clock timing.

RQ4 is deliberately separate: it streams a wall-clock episode through the real
MQTT subscriber and times publish→persist and publish→alert with a single-host
monotonic clock, because those latencies are only meaningful in real time.

RQ6 injects the known failure modes (duplicates, out-of-order, gaps, malformed
payloads, unknown vehicles, broker restart, transient DB failure) and records
clean-vs-degraded counts.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.exceptions import DatabaseError
from app.intelligence.models import TelemetryPoint
from app.mqtt.topics import build_telemetry_topic
from app.repositories.alert_repository import AlertRepository
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.alert_service import AlertService
from app.services.vehicle_health_service import VehicleHealthService
from evaluation.pipeline import metrics as M
from evaluation.pipeline.harness import (
    EvaluationDatabase,
    IsolatedBroker,
    Publisher,
    build_envelope,
    running_subscriber,
    wait_for_telemetry,
)
from evaluation.registry import SCENARIO_EXPECTED_RULES, SCENARIO_FAMILY, ScenarioSpec
from evaluation.scenarios import Episode, generate_episode

#: Monotonic pacing helper: how often we poll the DB while waiting.
_POLL_SECONDS = 0.005


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _expected_rules(scenario: str) -> tuple[tuple[str, ...], str]:
    return SCENARIO_EXPECTED_RULES[scenario]


def _observation(episode: Episode, vehicle_id: UUID, run_id: UUID) -> M.EpisodeObservation:
    expected_rules, min_severity = _expected_rules(episode.scenario)
    points = episode.points
    return M.EpisodeObservation(
        episode_id=episode.episode_id,
        scenario=episode.scenario,
        seed=episode.provenance.seed,
        run_id=str(run_id),
        onset=points[0].timestamp,
        end=points[-1].timestamp,
        duration_seconds=episode.provenance.duration_seconds,
        reference_family=SCENARIO_FAMILY[episode.scenario],
        expected_rule_ids=tuple(expected_rules),
        expected_min_severity=min_severity,
    )


def _shift(points: list[TelemetryPoint], delta: timedelta) -> list[TelemetryPoint]:
    return [
        TelemetryPoint(timestamp=point.timestamp + delta, values=point.values) for point in points
    ]


async def _monitor_pass(
    database: EvaluationDatabase,
    settings,
    vehicle_id: UUID,
    run_id: UUID,
    generated_at: datetime | None,
):
    """The monitor's per-vehicle work: analyse the active session, sync alerts."""
    async with database.session_factory() as session:
        vehicle_repository = VehicleRepository(session)
        health = VehicleHealthService(
            session,
            vehicle_repository,
            TelemetryRepository(session),
            HealthSnapshotRepository(session),
            settings,
        )
        snapshot = await health.analyze_live_vehicle(
            vehicle_id, run_id, generated_at=generated_at, persist=True
        )
        alerts = AlertService(session, vehicle_repository, AlertRepository(session))
        await alerts.sync_from_snapshot(snapshot)
    return snapshot


def _merge_alert_rows(
    rows: list[dict], known: dict[str, M.AlertObservation], *, provisional: bool
) -> None:
    """Fold DB rows into observations, remembering the provisional flag at first sight."""
    for row in rows:
        alert_id = row["alert_id"]
        existing = known.get(alert_id)
        if existing is None:
            known[alert_id] = M.AlertObservation(
                alert_id=alert_id,
                rule_id=row["rule_id"],
                severity=row["severity"],
                status=row["status"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                resolved_at=row["resolved_at"],
                occurrence_count=row["occurrence_count"],
                simulation_run_id=row["simulation_run_id"],
                provisional_at_create=provisional,
            )
        else:
            existing.status = row["status"]
            existing.severity = row["severity"]
            existing.resolved_at = row["resolved_at"]
            existing.occurrence_count = row["occurrence_count"]
            existing.last_seen_at = row["last_seen_at"]


def _event_id(run_id: UUID, index: int) -> str:
    return f"{run_id.hex[:18]}-{index:05d}"


async def _publish_points(
    publisher: Publisher, settings, vehicle_id: UUID, run_id: UUID, points: list[TelemetryPoint]
) -> list[str]:
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    event_ids: list[str] = []
    for index, point in enumerate(points):
        event_id = _event_id(run_id, index)
        event_ids.append(event_id)
        payload = build_envelope(vehicle_id, event_id, run_id, point.timestamp, point.values)
        await publisher.publish(topic, payload)
    return event_ids


async def _wait_persisted(
    database: EvaluationDatabase, vehicle_id: UUID, event_id: str, *, timeout: float
) -> datetime | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        created = await database.telemetry_created_at(vehicle_id, event_id)
        if created is not None:
            return created
        await asyncio.sleep(_POLL_SECONDS)
    return None


# --------------------------------------------------------------------------- #
# RQ3 — alert lifecycle via deterministic replay
# --------------------------------------------------------------------------- #


@dataclass
class AlertExperimentConfig:
    dataset_id: str
    scenarios: tuple[str, ...]
    seeds: tuple[int, ...]
    duration_seconds: float = 180.0


@dataclass
class AlertExperimentResult:
    episodes: list[M.EpisodeObservation] = field(default_factory=list)
    scope_counts: dict[str, int] = field(default_factory=dict)
    publish_stats: list[dict] = field(default_factory=list)


async def _publish_and_replay(
    database: EvaluationDatabase,
    settings,
    publisher: Publisher,
    vehicle_id: UUID,
    run_id: UUID,
    points: list[TelemetryPoint],
    observation: M.EpisodeObservation,
    *,
    known: dict[str, M.AlertObservation],
    scope_counts: dict[str, int] | None = None,
) -> int:
    """Publish a session's points, then replay the monitor once per sample."""
    async with running_subscriber(settings, database.session_factory):
        await _publish_points(publisher, settings, vehicle_id, run_id, points)
        persisted = await wait_for_telemetry(
            database, vehicle_id, len(points), run_id=run_id, timeout=60.0
        )
    for point in points:
        try:
            snapshot = await _monitor_pass(
                database, settings, vehicle_id, run_id, point.timestamp
            )
            observation.monitor_passes += 1
            observation.snapshots_persisted += 1
            context = snapshot.context_json or {}
            if scope_counts is not None:
                scope = str(context.get("analysis_scope"))
                scope_counts[scope] = scope_counts.get(scope, 0) + 1
            provisional = bool(context.get("provisional", False))
        except Exception:  # noqa: BLE001 - a failed pass is recorded, never hidden
            observation.failed_passes += 1
            provisional = True
        rows = await database.alert_rows(vehicle_id)
        _merge_alert_rows(rows, known, provisional=provisional)
    return persisted


async def run_alert_experiment(
    database: EvaluationDatabase,
    settings,
    publisher: Publisher,
    config: AlertExperimentConfig,
) -> AlertExperimentResult:
    """Publish + replay every scenario/seed episode through the real monitor path."""
    result = AlertExperimentResult()
    for scenario in config.scenarios:
        for seed in config.seeds:
            spec = ScenarioSpec(
                scenario=scenario, seed=seed, duration_seconds=config.duration_seconds
            )
            episode = generate_episode(config.dataset_id, spec)
            await database.truncate()
            vehicle_id = await database.create_vehicle()
            run_id = UUID(episode.provenance.run_id)
            observation = _observation(episode, vehicle_id, run_id)

            known: dict[str, M.AlertObservation] = {}
            persisted = await _publish_and_replay(
                database,
                settings,
                publisher,
                vehicle_id,
                run_id,
                episode.points,
                observation,
                known=known,
                scope_counts=result.scope_counts,
            )
            result.publish_stats.append(
                {
                    "episode_id": episode.episode_id,
                    "scenario": scenario,
                    "seed": seed,
                    "published": len(episode.points),
                    "persisted": persisted,
                    "dataloss": len(episode.points) - persisted,
                }
            )
            observation.alerts = list(known.values())
            result.episodes.append(observation)
    return result


async def run_recovery_experiment(
    database: EvaluationDatabase,
    settings,
    publisher: Publisher,
    *,
    dataset_id: str,
    scenarios: tuple[str, ...],
    seed: int,
    fault_seconds: float = 180.0,
    clean_seconds: float = 60.0,
) -> list[M.EpisodeObservation]:
    """Fault session, then a verifying clean session on the same vehicle.

    Auto-resolution requires a *definitive* pass that no longer observes the
    condition. A single 180 s run cannot demonstrate that, so recovery is modelled
    the honest way: a second, condition-free session on the same vehicle (the
    clean session's clock is shifted a day forward so the two sessions never
    overlap). Time-to-resolution is measured from the clean session's onset.
    """
    episodes: list[M.EpisodeObservation] = []
    for scenario in scenarios:
        fault_spec = ScenarioSpec(scenario=scenario, seed=seed, duration_seconds=fault_seconds)
        fault_episode = generate_episode(dataset_id, fault_spec)

        await database.truncate()
        vehicle_id = await database.create_vehicle()
        run_id = UUID(fault_episode.provenance.run_id)
        observation = _observation(fault_episode, vehicle_id, run_id)
        known: dict[str, M.AlertObservation] = {}
        await _publish_and_replay(
            database,
            settings,
            publisher,
            vehicle_id,
            run_id,
            fault_episode.points,
            observation,
            known=known,
        )

        clean_spec = ScenarioSpec(scenario="normal", seed=seed, duration_seconds=clean_seconds)
        clean_episode = generate_episode(dataset_id, clean_spec)
        clean_run_id = UUID(clean_episode.provenance.run_id)
        # The generator pins one epoch; shift the clean session forward a day so
        # the two sessions never share timestamps.
        clean_points = _shift(clean_episode.points, timedelta(days=1))
        observation.recovery_onset = clean_points[0].timestamp
        observation.recovery_note = (
            "clean 'normal' session on the same vehicle; the fault rule is absent, so a "
            "definitive pass asserts resolution"
        )
        await _publish_and_replay(
            database,
            settings,
            publisher,
            vehicle_id,
            clean_run_id,
            clean_points,
            observation,
            known=known,
        )
        observation.alerts = list(known.values())
        episodes.append(observation)
    return episodes


# --------------------------------------------------------------------------- #
# RQ4 — wall-clock pipeline latency
# --------------------------------------------------------------------------- #


@dataclass
class LatencyConfig:
    dataset_id: str
    scenario: str
    seeds: tuple[int, ...]
    samples: int = 60
    interval_seconds: float = 1.0


async def run_latency_experiment(
    database: EvaluationDatabase, settings, publisher: Publisher, config: LatencyConfig
) -> dict:
    """Stream a wall-clock session and time the real ingestion/alert path."""
    samples: list[dict] = []
    alert_latencies: list[dict] = []
    failures: list[dict] = []
    for seed in config.seeds:
        spec = ScenarioSpec(
            scenario=config.scenario,
            seed=seed,
            duration_seconds=float(config.samples),
            interval_seconds=config.interval_seconds,
        )
        episode = generate_episode(config.dataset_id, spec)
        await database.truncate()
        vehicle_id = await database.create_vehicle()
        run_id = UUID(episode.provenance.run_id)
        topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
        known_ids: set[str] = set()
        async with running_subscriber(settings, database.session_factory):
            for index, point in enumerate(episode.points):
                loop_start = time.perf_counter()
                event_id = _event_id(run_id, index)
                publish_ts = datetime.now(UTC)
                payload = build_envelope(vehicle_id, event_id, run_id, publish_ts, point.values)
                await publisher.publish(topic, payload)
                created_at = await _wait_persisted(
                    database, vehicle_id, event_id, timeout=10.0
                )
                if created_at is None:
                    failures.append(
                        {"seed": seed, "index": index, "stage": "persist", "error": "timeout"}
                    )
                pass_start = time.perf_counter()
                try:
                    snapshot = await _monitor_pass(
                        database, settings, vehicle_id, run_id, None
                    )
                except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                    failures.append(
                        {"seed": seed, "index": index, "stage": "monitor", "error": repr(exc)}
                    )
                    continue
                pass_ms = (time.perf_counter() - pass_start) * 1000.0
                context = snapshot.context_json or {}
                rows = await database.alert_rows(vehicle_id)
                for row in rows:
                    if row["alert_id"] in known_ids:
                        continue
                    known_ids.add(row["alert_id"])
                    alert_latencies.append(
                        {
                            "seed": seed,
                            "index": index,
                            "rule_id": row["rule_id"],
                            "severity": row["severity"],
                            "publish_to_alert_ms": (
                                row["first_seen_at"] - publish_ts
                            ).total_seconds()
                            * 1000.0,
                        }
                    )
                samples.append(
                    {
                        "seed": seed,
                        "index": index,
                        "event_id": event_id,
                        "ingest_ms": (
                            (created_at - publish_ts).total_seconds() * 1000.0
                            if created_at is not None
                            else None
                        ),
                        "monitor_pass_ms": pass_ms,
                        "engine_analysis_duration_ms": context.get("analysis_duration_ms"),
                        "analysis_scope": context.get("analysis_scope"),
                        "provisional": bool(context.get("provisional", False)),
                    }
                )
                remaining = config.interval_seconds - (time.perf_counter() - loop_start)
                if remaining > 0:
                    await asyncio.sleep(remaining)
    return {"samples": samples, "alert_latencies": alert_latencies, "failures": failures}


# --------------------------------------------------------------------------- #
# RQ6 — robustness under injected delivery faults
# --------------------------------------------------------------------------- #


class _FailingSessionContext:
    async def __aenter__(self):
        raise DatabaseError("injected transient database failure")

    async def __aexit__(self, *exc) -> bool:
        return False


class FlakySessionFactory:
    """Session factory that fails its first ``failures`` calls, then delegates."""

    def __init__(self, inner, *, failures: int) -> None:
        self._inner = inner
        self._remaining = failures
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            return _FailingSessionContext()
        return self._inner()


def _raw_envelope(
    *,
    vehicle_id: UUID,
    event_id: str,
    run_id: UUID | None = None,
    timestamp: str = "2026-01-01T00:00:00+00:00",
    telemetry: dict | None = None,
    schema_version: int = 2,
    extra: dict | None = None,
) -> bytes:
    body = {
        "schema_version": schema_version,
        "event_id": event_id,
        "vehicle_id": str(vehicle_id),
        "simulation_run_id": str(run_id) if run_id else None,
        "timestamp": timestamp,
        "telemetry": telemetry if telemetry is not None else {},
    }
    if extra:
        body.update(extra)
    return json.dumps(body).encode("utf-8")


async def _settle(
    database: EvaluationDatabase, vehicle_id: UUID, target: int, *, timeout: float
) -> int:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    count = 0
    while loop.time() < deadline:
        count = await database.count_telemetry(vehicle_id)
        if count >= target:
            return count
        await asyncio.sleep(0.05)
    return count


async def run_robustness_experiment(
    database: EvaluationDatabase,
    settings,
    broker: IsolatedBroker,
    *,
    dataset_id: str,
    seed: int = 7,
) -> list[dict]:
    """Inject the known delivery/DB/broker faults; record clean-vs-degraded counts."""
    base = generate_episode(
        dataset_id, ScenarioSpec(scenario="normal", seed=seed, duration_seconds=5.0)
    )
    point = base.points[0]
    results: list[dict] = []

    def valid_payload(
        vehicle_id: UUID, event_id: str, run_id: UUID, timestamp: datetime | None = None
    ) -> bytes:
        return build_envelope(
            vehicle_id, event_id, run_id, timestamp or point.timestamp, point.values
        )

    async def publish_many(publisher_obj, topic, payloads) -> int:
        for payload in payloads:
            await publisher_obj.publish(topic, payload)
        return len(payloads)

    # --- 1. clean baseline -------------------------------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            await publish_many(
                pub, topic, [valid_payload(vehicle_id, f"clean-{i}", run_id) for i in range(5)]
            )
        await _settle(database, vehicle_id, 5, timeout=20.0)
    persisted = await database.count_telemetry(vehicle_id)
    results.append(
        {
            "case": "clean_baseline",
            "description": "5 distinct valid samples delivered once each",
            "persisted": persisted,
            "expected_range": [5, 5],
            "passed": persisted == 5,
            "detail": "baseline: no duplicate loss, no drops",
        }
    )

    # --- 2. duplicate delivery (identical event_id) ------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    payload = valid_payload(vehicle_id, "dup-1", run_id)
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            await publish_many(pub, topic, [payload] * 5)
        await _settle(database, vehicle_id, 1, timeout=20.0)
        await asyncio.sleep(0.6)
    persisted = await database.count_telemetry(vehicle_id)
    results.append(
        {
            "case": "duplicate_delivery",
            "description": "the same (vehicle, event_id) delivered 5 times",
            "persisted": persisted,
            "expected_range": [1, 1],
            "passed": persisted == 1,
            "detail": "idempotent on (vehicle_id, source_event_id)",
        }
    )

    # --- 3. repeated ids across batches (flush-per-message) ----------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    sequence = ["r-a", "r-b", "r-a", "r-b"]
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            await publish_many(
                pub, topic, [valid_payload(vehicle_id, eid, run_id) for eid in sequence]
            )
        await _settle(database, vehicle_id, 2, timeout=20.0)
        await asyncio.sleep(0.6)
    persisted = await database.count_telemetry(vehicle_id)
    results.append(
        {
            "case": "repeated_event_ids",
            "description": "ids [a,b,a,b] replayed across separate flushes",
            "persisted": persisted,
            "expected_range": [2, 2],
            "passed": persisted == 2,
            "detail": "cross-batch dedup holds",
        }
    )

    # --- 4. out-of-order arrival ------------------------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    ordered = [point.timestamp + timedelta(seconds=i) for i in range(4)]
    arrival = [3, 1, 2, 0]
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            for i in arrival:
                await pub.publish(topic, valid_payload(vehicle_id, f"ooo-{i}", run_id, ordered[i]))
        await _settle(database, vehicle_id, 4, timeout=20.0)
        await asyncio.sleep(0.6)
    stored = await database.telemetry_timestamps(vehicle_id)
    persisted = len(stored)
    results.append(
        {
            "case": "out_of_order",
            "description": f"arrival order {arrival}, timestamp order 0..3",
            "persisted": persisted,
            "expected_range": [4, 4],
            "passed": persisted == 4 and stored == ordered,
            "detail": f"stored timestamps sorted == {stored == ordered}",
        }
    )

    # --- 5. delayed (late) message ----------------------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    delayed_ts = point.timestamp - timedelta(minutes=42)
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            await pub.publish(topic, valid_payload(vehicle_id, "late-1", run_id, delayed_ts))
            await pub.publish(topic, valid_payload(vehicle_id, "late-2", run_id, point.timestamp))
        await _settle(database, vehicle_id, 2, timeout=20.0)
    stored = await database.telemetry_timestamps(vehicle_id)
    results.append(
        {
            "case": "delayed_message",
            "description": "one sample stamped 42 min in the past",
            "persisted": len(stored),
            "expected_range": [2, 2],
            "passed": len(stored) == 2 and min(stored) == delayed_ts,
            "detail": "source timestamp preserved, not overwritten with arrival time",
        }
    )

    # --- 6. missing interval (gap) ----------------------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    now = datetime.now(UTC)
    gap_ts = [now - timedelta(seconds=s) for s in (30, 29, 28, 1)]
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            for i, ts in enumerate(gap_ts):
                await pub.publish(topic, valid_payload(vehicle_id, f"gap-{i}", run_id, ts))
        await _settle(database, vehicle_id, 4, timeout=20.0)
        try:
            snapshot = await _monitor_pass(database, settings, vehicle_id, run_id, None)
            findings = [f.get("rule_id") for f in (snapshot.context_json or {}).get("findings", [])]
        except Exception as exc:  # noqa: BLE001
            findings = [f"<monitor error: {exc!r}>"]
    persisted = await database.count_telemetry(vehicle_id)
    gap_signalled = any(
        rule in findings for rule in ("TELEMETRY_GAP", "LOW_DATA_COVERAGE", "LIMITED_DATA")
    )
    results.append(
        {
            "case": "missing_interval",
            "description": "samples at -30,-29,-28,-1 s (a 27 s gap)",
            "persisted": persisted,
            "expected_range": [4, 4],
            "passed": persisted == 4 and gap_signalled,
            "detail": f"data-quality findings: {sorted({f for f in findings if f})}",
        }
    )

    # --- 7. malformed / invalid payloads ----------------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    invalid: list[bytes] = [
        b"",  # empty
        b"{not json",  # invalid JSON
        b"[1, 2, 3]",  # JSON array, not an object
        json.dumps({"event_id": "missing-fields"}).encode(),  # missing required fields
        _raw_envelope(
            vehicle_id=vehicle_id,
            event_id="bad-extra",
            run_id=run_id,
            extra={"unexpected": True},
        ),
        _raw_envelope(
            vehicle_id=vehicle_id,
            event_id="bad-throttle",
            run_id=run_id,
            telemetry={"throttle_position": 150.0},
        ),
        _raw_envelope(vehicle_id=vehicle_id, event_id="naive-ts", run_id=run_id, timestamp="2026-01-01T00:00:00"),
        _raw_envelope(
            vehicle_id=vehicle_id, event_id="bad-version", run_id=run_id, schema_version=0
        ),
    ]
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            await publish_many(pub, topic, invalid)
            await pub.publish(topic, valid_payload(vehicle_id, "after-invalid", run_id))
        await _settle(database, vehicle_id, 1, timeout=20.0)
        await asyncio.sleep(0.8)
    persisted = await database.count_telemetry(vehicle_id)
    results.append(
        {
            "case": "malformed_payloads",
            "description": "8 invalid envelopes (JSON/schema/tz/version/bounds) then 1 valid",
            "persisted": persisted,
            "expected_range": [1, 1],
            "passed": persisted == 1,
            "detail": "invalid messages discarded; stream survived to persist the next valid one",
        }
    )

    # --- 8. unknown vehicle ------------------------------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    unknown_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    unknown_topic = build_telemetry_topic(unknown_id, settings.mqtt_topic_prefix)
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            await pub.publish(unknown_topic, valid_payload(unknown_id, "unknown-1", run_id))
            await pub.publish(
                topic, valid_payload(vehicle_id, "known-after-unknown", run_id)
            )
        await _settle(database, vehicle_id, 1, timeout=20.0)
        await asyncio.sleep(0.8)
    persisted = await database.count_telemetry(vehicle_id)
    unknown_persisted = await database.count_telemetry(unknown_id)
    results.append(
        {
            "case": "unknown_vehicle",
            "description": "a valid envelope for an unregistered vehicle, then a known one",
            "persisted": persisted,
            "expected_range": [1, 1],
            "passed": persisted == 1 and unknown_persisted == 0,
            "detail": f"unknown vehicle rows persisted: {unknown_persisted}",
        }
    )

    # --- 9. transient database failure (retried) --------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    flaky = FlakySessionFactory(database.session_factory, failures=2)
    async with running_subscriber(settings, flaky):
        async with Publisher(settings) as pub:
            await publish_many(
                pub, topic, [valid_payload(vehicle_id, f"flaky-{i}", run_id) for i in range(4)]
            )
        await _settle(database, vehicle_id, 4, timeout=30.0)
    persisted = await database.count_telemetry(vehicle_id)
    results.append(
        {
            "case": "transient_db_failure",
            "description": "first 2 session acquisitions raise DatabaseError (retry_attempts=3)",
            "persisted": persisted,
            "expected_range": [4, 4],
            "passed": persisted == 4,
            "detail": f"session-factory calls: {flaky.calls}; all samples eventually persisted",
        }
    )

    # --- 10. broker restart ------------------------------------------------- #
    await database.truncate()
    vehicle_id = await database.create_vehicle()
    run_id = uuid4()
    topic = build_telemetry_topic(vehicle_id, settings.mqtt_topic_prefix)
    reconnect_after: float | None = None
    async with running_subscriber(settings, database.session_factory):
        async with Publisher(settings) as pub:
            await publish_many(
                pub, topic, [valid_payload(vehicle_id, f"pre-{i}", run_id) for i in range(3)]
            )
        await _settle(database, vehicle_id, 3, timeout=20.0)
        broker.restart()
        t0 = time.perf_counter()
        for attempt in range(40):
            async with Publisher(settings) as pub:
                await pub.publish(topic, valid_payload(vehicle_id, f"probe-{attempt}", run_id))
            if await _wait_persisted(
                database, vehicle_id, f"probe-{attempt}", timeout=1.0
            ):
                reconnect_after = time.perf_counter() - t0
                break
            await asyncio.sleep(0.5)
        async with Publisher(settings) as pub:
            await publish_many(
                pub, topic, [valid_payload(vehicle_id, f"post-{i}", run_id) for i in range(3)]
            )
        await _settle(database, vehicle_id, 6, timeout=20.0)
    persisted = await database.count_telemetry(vehicle_id)
    results.append(
        {
            "case": "broker_restart",
            "description": "broker killed and relaunched mid-stream, then more samples",
            "persisted": persisted,
            "expected_range": [4, 1000],
            "passed": persisted >= 6 and reconnect_after is not None,
            "detail": (
                f"subscriber reconnected after {reconnect_after:.1f}s"
                if reconnect_after is not None
                else "subscriber never reconnected"
            ),
        }
    )
    return results

