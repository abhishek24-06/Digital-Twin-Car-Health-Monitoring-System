"""Derived telemetry pipeline state for the read-only ``/workflow/state`` endpoint.

This module turns *real* process and database signals into an honest snapshot of
how far a vehicle's telemetry has actually flowed. It never bridges
per-message telemetry onto the workflow bus, never invents progress, and never
emits ``WAITING``: a stage with no real signal is simply omitted. Every stage is
explicitly marked ``observation="derived"`` so derived state is never presented
as a directly observed event.

Freshness is derived from the *correct* clock per subsystem: telemetry stages use
the newest persisted row's ``timestamp`` and the short telemetry window; the
health stages use the last snapshot's ``generated_at`` against the monitor's own
evaluation cadence. A monitor that is enabled but whose most recent evaluation
failed is reported as ``DEGRADED`` with the failure time and reason, rather than
a misleading "awaiting a snapshot".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas.workflow import (
    StageState,
    TelemetryStage,
    VehicleTelemetryState,
    WorkflowStatus,
)
from app.services.simulation_manager import SimulationManager
from app.services.subscriber_manager import SubscriberSupervisor
from app.services.telemetry_freshness import (
    STALE_AFTER_SECONDS,
    snapshot_stale_after_seconds,
)


@dataclass(frozen=True)
class HealthEvaluationFailure:
    """The most recent failed health evaluation observed for a vehicle.

    Sourced from the in-memory workflow event bus (the monitor publishes an
    ``error`` event per failed vehicle). Kept deliberately small so the pure
    derivation service does not depend on the full event schema.
    """

    at: datetime
    message: str


def _fresh(at: datetime | None, now: datetime, *, stale_after: float) -> bool:
    """True when a real timestamp is present and within ``stale_after`` seconds."""
    if at is None:
        return False
    return (now - at).total_seconds() <= stale_after


async def build_vehicle_state(
    session: AsyncSession,
    manager: SimulationManager,
    subscriber: SubscriberSupervisor,
    *,
    vehicle_id: UUID,
    now: datetime | None = None,
    last_health_failure: HealthEvaluationFailure | None = None,
) -> VehicleTelemetryState:
    """Build the derived telemetry pipeline snapshot for one vehicle.

    Read-only: it reads the simulation supervisor, the subscriber supervisor,
    persisted telemetry rows and the latest health snapshot, then reports only
    the stages backed by a real signal.
    """
    now = now or datetime.now(UTC)
    settings = get_settings()

    simulation = await manager.get_status(vehicle_id)
    subscriber_health = await subscriber.health()

    telemetry_repo = TelemetryRepository(session)
    latest = (await telemetry_repo.get_latest_timestamps([vehicle_id])).get(vehicle_id)
    messages_received = await telemetry_repo.count_for_vehicle(vehicle_id)
    snapshot = await HealthSnapshotRepository(session).get_latest_by_vehicle(vehicle_id)

    lifecycle = simulation.status
    has_rows = messages_received > 0 or latest is not None
    fresh = _fresh(latest, now, stale_after=STALE_AFTER_SECONDS)
    subscriber_running = subscriber_health.running
    snapshot_at = snapshot.generated_at if snapshot is not None else None

    # Snapshots age on the monitor's evaluation cadence, not the telemetry window.
    snapshot_stale_after = snapshot_stale_after_seconds(
        monitor_min_seconds=getattr(settings, "health_monitor_min_seconds", 60.0),
        monitor_interval_seconds=getattr(settings, "health_monitor_interval_seconds", 10.0),
    )
    snapshot_fresh = _fresh(snapshot_at, now, stale_after=snapshot_stale_after)
    # A failure only reflects current engine state while it is newer than the
    # last successful snapshot; a later snapshot supersedes it.
    failure_current = last_health_failure is not None and (
        snapshot_at is None or last_health_failure.at > snapshot_at
    )

    stages: list[StageState] = []

    # Simulator lifecycle (only meaningful while starting/running/failed).
    if lifecycle == "starting":
        stages.append(
            StageState(
                stage=TelemetryStage.SIMULATOR,
                status=WorkflowStatus.STARTED,
                at=simulation.started_at,
                detail="Simulator starting",
            )
        )
    elif lifecycle == "running" and simulation.error:
        stages.append(
            StageState(
                stage=TelemetryStage.SIMULATOR,
                status=WorkflowStatus.DEGRADED,
                at=simulation.started_at,
                detail=simulation.error,
            )
        )
    elif lifecycle == "running":
        stages.append(
            StageState(
                stage=TelemetryStage.SIMULATOR,
                status=WorkflowStatus.SUCCESS,
                at=simulation.started_at,
                detail="Simulator running",
            )
        )
    elif lifecycle == "error":
        stages.append(
            StageState(
                stage=TelemetryStage.SIMULATOR,
                status=WorkflowStatus.DEGRADED,
                at=simulation.started_at,
                detail=simulation.error or "Simulator error",
            )
        )

    # Publish leg: only while the simulator is active.
    if lifecycle in ("starting", "running"):
        stages.append(
            StageState(
                stage=TelemetryStage.MQTT_PUBLISH,
                status=WorkflowStatus.SUCCESS if fresh else WorkflowStatus.DEGRADED,
                at=latest,
                detail=(
                    "Telemetry is being published to the broker"
                    if fresh
                    else "Simulator is active but no recent telemetry has been persisted"
                ),
            )
        )

    # Broker: only when a subscriber is alive and a datapoint has ever flowed.
    # A stopped subscriber is reported on its own stage; it must never be
    # presented as the broker failing.
    if subscriber_running and has_rows:
        stages.append(
            StageState(
                stage=TelemetryStage.MQTT_BROKER,
                status=WorkflowStatus.SUCCESS if fresh else WorkflowStatus.DEGRADED,
                at=latest,
                detail=(
                    "Telemetry flowing"
                    if fresh
                    else "Subscriber is alive but no recent telemetry flow has been observed"
                ),
            )
        )

    # Subscriber health is always known from the supervisor.
    stages.append(
        StageState(
            stage=TelemetryStage.MQTT_SUBSCRIBER,
            status=(WorkflowStatus.SUCCESS if subscriber_running else WorkflowStatus.ERROR),
            at=subscriber_health.started_at,
            detail=(
                "Subscriber running"
                if subscriber_running
                else (subscriber_health.last_error or "Subscriber is not running")
            ),
        )
    )

    # Parser + Postgres: only when rows actually exist. The high-frequency
    # per-message parse is not bridged; this means "a confirmed healthy flow is
    # observed", not "this exact message was parsed".
    if has_rows:
        stages.append(
            StageState(
                stage=TelemetryStage.PARSER,
                status=WorkflowStatus.SUCCESS if fresh else WorkflowStatus.DEGRADED,
                at=latest,
                detail=(
                    "Receiving valid telemetry"
                    if fresh
                    else "Valid telemetry was received, but no recent sample has been persisted"
                ),
            )
        )
        stages.append(
            StageState(
                stage=TelemetryStage.POSTGRES,
                status=WorkflowStatus.SUCCESS if fresh else WorkflowStatus.DEGRADED,
                at=latest,
                detail=("Newest telemetry is fresh" if fresh else "Newest telemetry is stale"),
            )
        )

    # Health engine: only when the monitor is enabled.
    if settings.health_monitor_enabled:
        if failure_current:
            engine_status = WorkflowStatus.DEGRADED
            engine_at = last_health_failure.at
            engine_detail = f"Last evaluation failed: {last_health_failure.message}"
        elif snapshot_at is None:
            engine_status = WorkflowStatus.RUNNING
            engine_at = None
            engine_detail = "Health monitor is enabled; no snapshot has been produced yet"
        elif snapshot_fresh:
            engine_status = WorkflowStatus.SUCCESS
            engine_at = snapshot_at
            engine_detail = "Health monitor produced a recent snapshot"
        elif fresh:
            # Telemetry is arriving but no newer snapshot was produced, so the
            # engine itself is lagging rather than waiting for data.
            engine_status = WorkflowStatus.DEGRADED
            engine_at = snapshot_at
            engine_detail = "Health monitor has not evaluated the recent telemetry"
        else:
            # No new telemetry to score: the engine is idle, not faulty.
            engine_status = WorkflowStatus.RUNNING
            engine_at = snapshot_at
            engine_detail = "Awaiting new telemetry before the next evaluation"
        stages.append(
            StageState(
                stage=TelemetryStage.HEALTH_ENGINE,
                status=engine_status,
                at=engine_at,
                detail=engine_detail,
            )
        )

    # Health snapshot: only when one exists.
    if snapshot is not None:
        if failure_current:
            snapshot_status = WorkflowStatus.DEGRADED
            snapshot_detail = "No snapshot has been persisted since the last failed evaluation"
        elif snapshot_fresh:
            snapshot_status = WorkflowStatus.SUCCESS
            snapshot_detail = "Snapshot is fresh"
        else:
            snapshot_status = WorkflowStatus.DEGRADED
            snapshot_detail = "Snapshot is stale"
        stages.append(
            StageState(
                stage=TelemetryStage.HEALTH_SNAPSHOT,
                status=snapshot_status,
                at=snapshot_at,
                detail=snapshot_detail,
            )
        )

    degraded_reason = simulation.error
    if degraded_reason is None and has_rows and not fresh:
        degraded_reason = "Newest telemetry is stale"

    return VehicleTelemetryState(
        vehicle_id=vehicle_id,
        simulation_status=lifecycle,
        stages=stages,
        last_telemetry_at=latest,
        messages_received=messages_received,
        snapshot_at=snapshot_at,
        degraded_reason=degraded_reason,
        updated_at=now,
    )
