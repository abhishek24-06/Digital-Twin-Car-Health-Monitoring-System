"""Derived telemetry pipeline state tests (hermetic: fake process/DB signals).

``build_vehicle_state`` must describe how far a vehicle's telemetry actually
flowed using *real* signals only (simulation lifecycle, subscriber health,
persisted telemetry rows, health snapshot). No stage may ever be
``WorkflowStatus.WAITING`` and stages with no signal are omitted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from app.schemas.workflow import TelemetryStage, WorkflowStatus
from app.services import telemetry_pipeline_state as tps
from app.services.simulation_manager import SimulationStatus
from app.services.subscriber_manager import SubscriberHealth

VEHICLE_ID = UUID("00000000-0000-0000-0000-000000000001")


class _FakeManager:
    def __init__(self, status: SimulationStatus) -> None:
        self._status = status

    async def get_status(self, vehicle_id: UUID) -> SimulationStatus:
        return self._status


class _FakeSubscriber:
    def __init__(self, running: bool) -> None:
        self._running = running

    async def health(self) -> SubscriberHealth:
        return SubscriberHealth(running=self._running)


class _FakeTelemetryRepo:
    last: datetime | None = None
    count: int = 0

    def __init__(self, session) -> None:  # noqa: ANN001
        self._session = session

    async def get_latest_timestamps(self, vehicle_ids: list[UUID]) -> dict[UUID, datetime]:
        if self.last is None:
            return {}
        return {vehicle_ids[0]: self.last}

    async def count_for_vehicle(self, vehicle_id: UUID) -> int:
        return self.count


class _Snapshot:
    def __init__(self, generated_at: datetime) -> None:
        self.generated_at = generated_at


class _FakeHealthSnapshotRepo:
    snapshot: _Snapshot | None = None

    def __init__(self, session) -> None:  # noqa: ANN001
        self._session = session

    async def get_latest_by_vehicle(self, vehicle_id: UUID):
        return self.snapshot


def _status(lifecycle: str, *, started_at=None, error=None) -> SimulationStatus:
    return SimulationStatus(
        vehicle_id=VEHICLE_ID,
        status=lifecycle,
        scenario="normal",
        interval_seconds=1.0,
        seed=1,
        started_at=started_at,
        error=error,
    )


async def _build(
    monkeypatch,
    *,
    lifecycle: str = "running",
    subscriber_running: bool = True,
    last: datetime | None = None,
    count: int = 0,
    snapshot: _Snapshot | None = None,
    monitor_enabled: bool = False,
    started_at: datetime | None = None,
    error: str | None = None,
    failure: tps.HealthEvaluationFailure | None = None,
    monitor_min_seconds: float = 60.0,
    monitor_interval_seconds: float = 10.0,
    now: datetime,
):
    monkeypatch.setattr(tps, "TelemetryRepository", _FakeTelemetryRepo)
    monkeypatch.setattr(tps, "HealthSnapshotRepository", _FakeHealthSnapshotRepo)
    monkeypatch.setattr(
        tps,
        "get_settings",
        lambda: SimpleNamespace(
            health_monitor_enabled=monitor_enabled,
            health_monitor_min_seconds=monitor_min_seconds,
            health_monitor_interval_seconds=monitor_interval_seconds,
        ),
    )
    _FakeTelemetryRepo.last = last
    _FakeTelemetryRepo.count = count
    _FakeHealthSnapshotRepo.snapshot = snapshot
    return await tps.build_vehicle_state(
        None,
        _FakeManager(_status(lifecycle, started_at=started_at, error=error)),
        _FakeSubscriber(subscriber_running),
        vehicle_id=VEHICLE_ID,
        now=now,
        last_health_failure=failure,
    )


def _by_stage(state):
    return {stage.stage: stage for stage in state.stages}


async def test_running_fresh_flow_is_success(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now - timedelta(seconds=2),
        count=42,
        started_at=now - timedelta(minutes=5),
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.SIMULATOR].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.MQTT_PUBLISH].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.MQTT_BROKER].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.MQTT_SUBSCRIBER].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.PARSER].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.PARSER].detail == "Receiving valid telemetry"
    assert stages[TelemetryStage.POSTGRES].status == WorkflowStatus.SUCCESS
    assert state.messages_received == 42
    assert all(stage.observation == "derived" for stage in state.stages)


async def test_running_stale_flow_degrades_broker(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now - timedelta(seconds=120),
        count=42,
        started_at=now - timedelta(minutes=10),
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.MQTT_BROKER].status == WorkflowStatus.DEGRADED
    assert "no recent telemetry flow" in (stages[TelemetryStage.MQTT_BROKER].detail or "")
    assert stages[TelemetryStage.POSTGRES].status == WorkflowStatus.DEGRADED
    # A stale flow must never be reported as actively "receiving" telemetry: the
    # parser stage distinguishes "received before" from "persisted recently".
    assert stages[TelemetryStage.PARSER].status == WorkflowStatus.DEGRADED
    assert stages[TelemetryStage.PARSER].detail == (
        "Valid telemetry was received, but no recent sample has been persisted"
    )


async def test_subscriber_stopped_reports_error_and_omits_broker(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=False,
        last=now - timedelta(seconds=120),
        count=42,
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.MQTT_SUBSCRIBER].status == WorkflowStatus.ERROR
    # A stopped subscriber must never be reported as the broker failing.
    assert TelemetryStage.MQTT_BROKER not in stages


async def test_no_samples_omits_parser_and_postgres(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="stopped",
        subscriber_running=True,
        last=None,
        count=0,
        now=now,
    )

    stages = _by_stage(state)
    assert TelemetryStage.PARSER not in stages
    assert TelemetryStage.POSTGRES not in stages
    # Stopped simulator: no lifecycle stage at all.
    assert TelemetryStage.SIMULATOR not in stages


async def test_never_emits_waiting(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="starting",
        subscriber_running=True,
        last=None,
        count=0,
        now=now,
    )
    # ``waiting`` is a frontend-only state; the backend vocabulary must never
    # carry it. It is not even a member of ``WorkflowStatus``, so assert on the
    # wire values to make the guarantee explicit.
    assert all(stage.status.value != "waiting" for stage in state.stages)
    assert all(stage.observation == "derived" for stage in state.stages)


async def test_simulator_error_is_degraded(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="error",
        subscriber_running=True,
        last=None,
        count=0,
        error="simulator crashed",
        now=now,
    )
    stages = _by_stage(state)
    assert stages[TelemetryStage.SIMULATOR].status == WorkflowStatus.DEGRADED
    assert stages[TelemetryStage.SIMULATOR].detail == "simulator crashed"
    assert state.degraded_reason == "simulator crashed"


async def test_health_engine_and_snapshot_stages(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now,
        count=10,
        snapshot=_Snapshot(now - timedelta(seconds=5)),
        monitor_enabled=True,
        now=now,
    )
    stages = _by_stage(state)
    assert stages[TelemetryStage.HEALTH_ENGINE].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.HEALTH_SNAPSHOT].status == WorkflowStatus.SUCCESS
    assert state.snapshot_at == now - timedelta(seconds=5)


async def test_health_engine_omitted_when_disabled(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now,
        count=10,
        snapshot=_Snapshot(now - timedelta(seconds=5)),
        monitor_enabled=False,
        now=now,
    )
    stages = _by_stage(state)
    assert TelemetryStage.HEALTH_ENGINE not in stages
    assert TelemetryStage.HEALTH_SNAPSHOT in stages


# ---------------------------------------------------------------------------
# Freshness must use the *correct* clock per subsystem: snapshot age is judged
# against the health monitor's own cadence, never the 30s telemetry window.
# ---------------------------------------------------------------------------


async def test_snapshot_within_monitor_cadence_is_not_stale(monkeypatch) -> None:
    """A snapshot younger than the monitor cadence is fresh, not stale.

    The monitor evaluates a vehicle at most once per ``monitor_min_seconds``;
    reusing the 30s telemetry window falsely flagged a healthy snapshot as stale
    for most of every cycle.
    """
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now,
        count=10,
        snapshot=_Snapshot(now - timedelta(seconds=80)),
        monitor_enabled=True,
        monitor_min_seconds=60.0,
        monitor_interval_seconds=10.0,
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.HEALTH_ENGINE].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.HEALTH_SNAPSHOT].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.HEALTH_SNAPSHOT].detail == "Snapshot is fresh"


async def test_snapshot_beyond_cadence_is_degraded(monkeypatch) -> None:
    """A snapshot older than cadence + tolerance while telemetry flows is stale."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now,
        count=10,
        snapshot=_Snapshot(now - timedelta(seconds=200)),
        monitor_enabled=True,
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.HEALTH_ENGINE].status == WorkflowStatus.DEGRADED
    assert stages[TelemetryStage.HEALTH_SNAPSHOT].status == WorkflowStatus.DEGRADED
    assert stages[TelemetryStage.HEALTH_SNAPSHOT].detail == "Snapshot is stale"


async def test_engine_idle_when_no_new_telemetry(monkeypatch) -> None:
    """With no new telemetry the engine is idle, not faulty."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now - timedelta(seconds=200),
        count=10,
        snapshot=_Snapshot(now - timedelta(seconds=200)),
        monitor_enabled=True,
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.HEALTH_ENGINE].status == WorkflowStatus.RUNNING
    assert stages[TelemetryStage.HEALTH_SNAPSHOT].status == WorkflowStatus.DEGRADED


async def test_last_health_failure_is_surfaced(monkeypatch) -> None:
    """A failed evaluation newer than the snapshot reports degraded + reason."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now,
        count=10,
        snapshot=_Snapshot(now - timedelta(seconds=10)),
        monitor_enabled=True,
        failure=tps.HealthEvaluationFailure(
            at=now - timedelta(seconds=5), message="statement timeout"
        ),
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.HEALTH_ENGINE].status == WorkflowStatus.DEGRADED
    assert "statement timeout" in (stages[TelemetryStage.HEALTH_ENGINE].detail or "")
    assert stages[TelemetryStage.HEALTH_ENGINE].at == now - timedelta(seconds=5)
    assert stages[TelemetryStage.HEALTH_SNAPSHOT].status == WorkflowStatus.DEGRADED


async def test_newer_snapshot_supersedes_older_failure(monkeypatch) -> None:
    """A successful evaluation after the failure clears the degraded reason."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now,
        count=10,
        snapshot=_Snapshot(now - timedelta(seconds=10)),
        monitor_enabled=True,
        failure=tps.HealthEvaluationFailure(
            at=now - timedelta(seconds=30), message="statement timeout"
        ),
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.HEALTH_ENGINE].status == WorkflowStatus.SUCCESS
    assert stages[TelemetryStage.HEALTH_SNAPSHOT].status == WorkflowStatus.SUCCESS


async def test_missing_snapshot_is_honest_running_not_stale(monkeypatch) -> None:
    """No snapshot yet is ``running`` with no timestamp, never a stale claim."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now,
        count=10,
        snapshot=None,
        monitor_enabled=True,
        now=now,
    )

    stages = _by_stage(state)
    assert stages[TelemetryStage.HEALTH_ENGINE].status == WorkflowStatus.RUNNING
    assert stages[TelemetryStage.HEALTH_ENGINE].at is None
    assert TelemetryStage.HEALTH_SNAPSHOT not in stages


async def test_observed_timestamps_are_timezone_aware(monkeypatch) -> None:
    """Derived timestamps stay UTC-aware so comparisons never mix naive/aware."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    state = await _build(
        monkeypatch,
        lifecycle="running",
        subscriber_running=True,
        last=now - timedelta(seconds=2),
        count=10,
        snapshot=_Snapshot(now - timedelta(seconds=5)),
        monitor_enabled=True,
        started_at=now - timedelta(minutes=5),
        now=now,
    )

    assert state.snapshot_at is not None
    assert state.snapshot_at.utcoffset() is not None
    for stage in state.stages:
        if stage.at is not None:
            assert stage.at.utcoffset() is not None
