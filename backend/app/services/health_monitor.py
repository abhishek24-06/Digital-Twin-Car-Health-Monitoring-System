"""Background health evaluation and autonomous escalation.

The telemetry route only persists readings — nothing in the request path ever
scores them, so a vehicle could stream faults indefinitely without a snapshot
being produced. This service closes that gap: each pass finds vehicles whose
telemetry has moved on since their last health snapshot, re-analyses them, and
escalates critical results into the LangGraph diagnosis pipeline (with the
agent's own cooldown deduplicating repeats).

A failure on one vehicle never aborts the pass; it is recorded in
``MonitorPassResult.errors`` and the loop moves on.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.service import AgentService
from app.core.config import Settings, get_settings
from app.models.health_snapshot import HealthSnapshot
from app.models.user import User
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.workflow import (
    WorkflowStage,
    WorkflowStatus,
    WorkflowType,
    sanitize_metadata,
)
from app.services.alert_service import AlertService
from app.services.vehicle_health_service import VehicleHealthService
from app.services.workflow_event_bus import publish_workflow_event

logger = logging.getLogger(__name__)


class HealthEvaluator(Protocol):
    """The slice of VehicleHealthService the monitor depends on."""

    async def analyze_vehicle(
        self, vehicle_id: UUID, window_minutes: float | None = None
    ) -> HealthSnapshot: ...

    async def analyze_live_vehicle(self, vehicle_id: UUID, run_id: UUID) -> HealthSnapshot: ...


class CriticalEventEscalator(Protocol):
    """The slice of AgentService the monitor depends on."""

    async def run_critical_event(
        self,
        vehicle_id: UUID,
        rule_ids: list[str] | None = None,
        *,
        user: User | None = None,
    ) -> Any: ...


HealthServiceFactory = Callable[[AsyncSession], HealthEvaluator]
AgentServiceFactory = Callable[[AsyncSession], CriticalEventEscalator]
AlertServiceFactory = Callable[[AsyncSession], AlertService]
#: Resolves the *active* simulator run id for a vehicle (or None when the
#: vehicle has no current run). The monitor only ever evaluates current-session
#: evidence; stopped vehicles are not due for a fresh assessment.
RunResolver = Callable[[UUID], Awaitable[UUID | None]]


def should_escalate(health_status: str) -> bool:
    """Only a definitive critical classification warrants an autonomous diagnosis.

    "attention", "unknown", "no_data" and "limited_data" are deliberately
    excluded: attention is a watch-and-wait signal, no_data has nothing to
    escalate, and a limited-data result is a provisional rating with low
    confidence (Phase 10) — not worth spending an LLM call on until enough
    telemetry confirms it.
    """
    return health_status == "critical"


@dataclass
class MonitorPassResult:
    """Counters for a single pass, suitable for logging and tests."""

    considered: int = 0
    evaluated: int = 0
    escalated: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _default_health_service(session: AsyncSession) -> VehicleHealthService:
    return VehicleHealthService(
        session=session,
        vehicle_repository=VehicleRepository(session),
        telemetry_repository=TelemetryRepository(session),
        health_repository=HealthSnapshotRepository(session),
    )


def _default_agent_service(session: AsyncSession) -> AgentService:
    return AgentService(session)


class HealthMonitorService:
    """Runs one evaluation pass over the vehicles that are due."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        settings: Settings | None = None,
        health_service_factory: HealthServiceFactory | None = None,
        agent_service_factory: AgentServiceFactory | None = None,
        alert_service_factory: AlertServiceFactory | None = None,
        run_resolver: RunResolver | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or get_settings()
        self._health_service_factory = health_service_factory or _default_health_service
        self._agent_service_factory = agent_service_factory or _default_agent_service
        self._alert_service_factory = alert_service_factory
        self._run_resolver = run_resolver

    async def run_pass(self) -> MonitorPassResult:
        """Evaluate every due vehicle once and escalate critical results.

        Returns immediately when the monitor is disabled. Each vehicle gets its
        own session so that one failure cannot poison the rest of the pass.
        """
        if not self._settings.health_monitor_enabled:
            return MonitorPassResult()

        cutoff = datetime.now(UTC) - timedelta(seconds=self._settings.health_monitor_min_seconds)
        async with self._session_factory() as session:
            due = await HealthSnapshotRepository(session).list_vehicle_ids_with_newer_telemetry(
                older_than=cutoff,
                limit=self._settings.health_monitor_max_vehicles,
            )

        await publish_workflow_event(
            workflow=WorkflowType.HEALTH,
            stage=WorkflowStage.HEALTH_ANALYSIS_STARTED,
            status=WorkflowStatus.STARTED,
            message=f"Health monitor pass started for {len(due)} vehicles",
            metadata=sanitize_metadata(
                {
                    "vehicles_considered": len(due),
                    "cutoff_seconds": self._settings.health_monitor_min_seconds,
                }
            ),
        )

        result = MonitorPassResult(considered=len(due))
        for vehicle_id in due:
            if not await self._evaluate(vehicle_id, result):
                continue
            if await self._escalate(vehicle_id, result):
                result.escalated += 1

        if result.considered:
            logger.info(
                "health monitor pass: considered=%d evaluated=%d escalated=%d failed=%d",
                result.considered,
                result.evaluated,
                result.escalated,
                result.failed,
            )
            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.HEALTH_ANALYSIS_STARTED,
                status=WorkflowStatus.SUCCESS,
                message="Health monitor pass completed",
                metadata=sanitize_metadata(
                    {
                        "considered": result.considered,
                        "evaluated": result.evaluated,
                        "escalated": result.escalated,
                        "failed": result.failed,
                    }
                ),
            )
        return result

    async def _evaluate(self, vehicle_id: UUID, result: MonitorPassResult) -> bool:
        """Analyse the *current session* of one vehicle.

        Returns False when the analysis failed or when there is no active run
        to evaluate. A vehicle with no active simulator run is simply not due:
        it is skipped silently (never counted as evaluated or failed) so a
        stopped vehicle's old snapshot is never overwritten by a misleading
        fresh-window assessment.
        """
        try:
            if self._run_resolver is not None:
                run_id = await self._run_resolver(vehicle_id)
                if run_id is None:
                    logger.info(
                        "health monitor: vehicle %s has no active run; skipping current-session evaluation",
                        vehicle_id,
                    )
                    return False

            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.TELEMETRY_WINDOW_LOADED,
                status=WorkflowStatus.RUNNING,
                message=f"Loading current-session telemetry window for vehicle {vehicle_id}",
                vehicle_id=str(vehicle_id),
                metadata=sanitize_metadata(
                    {
                        "simulation_run_id": (
                            str(run_id) if self._run_resolver is not None else None
                        ),
                        "evaluation": (
                            "live_current_run"
                            if self._run_resolver is not None
                            else "legacy_window"
                        ),
                    }
                ),
            )

            async with self._session_factory() as session:
                if self._run_resolver is not None:
                    snapshot = await self._health_service_factory(session).analyze_live_vehicle(
                        vehicle_id, run_id
                    )
                else:
                    # Legacy monitor wiring (no run resolver): fall back to the
                    # historical window analysis for backward compatibility.
                    snapshot = await self._health_service_factory(session).analyze_vehicle(
                        vehicle_id
                    )

                # Materialize persisted alerts from this evaluation. Isolated so
                # an alert-store failure degrades alerts only: the snapshot (and
                # the pass) still succeeds.
                if self._alert_service_factory is not None:
                    try:
                        await self._alert_service_factory(session).sync_from_snapshot(snapshot)
                    except Exception:
                        logger.exception("health monitor: alert sync failed for %s", vehicle_id)

            # Extract data sufficiency from context_json
            data_sufficiency = snapshot.context_json.get("data_sufficiency", "unknown")
            sample_count = snapshot.context_json.get("data_quality", {}).get("sample_count", 0)
            coverage = snapshot.context_json.get("data_quality", {}).get("coverage_ratio", 0.0)
            simulation_run_id = snapshot.context_json.get("simulation_run_id")
            live_sufficiency = snapshot.context_json.get("live_sufficiency") or {}

            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.DATA_SUFFICIENCY_EVALUATED,
                status=WorkflowStatus.SUCCESS,
                message=f"Data sufficiency: {data_sufficiency} for vehicle {vehicle_id}",
                vehicle_id=str(vehicle_id),
                metadata=sanitize_metadata(
                    {
                        "sufficiency": data_sufficiency,
                        "sample_count": sample_count,
                        "coverage": coverage,
                        "simulation_run_id": (
                            str(simulation_run_id) if simulation_run_id is not None else None
                        ),
                        "live_policy_met": live_sufficiency.get("policy_met"),
                    }
                ),
            )

            baselines = snapshot.context_json.get("baselines", [])
            if baselines:
                await publish_workflow_event(
                    workflow=WorkflowType.HEALTH,
                    stage=WorkflowStage.BASELINE_COMPARISON_COMPLETED,
                    status=WorkflowStatus.SUCCESS,
                    message=f"Baseline comparison completed for vehicle {vehicle_id} ({len(baselines)} baselines)",
                    vehicle_id=str(vehicle_id),
                    metadata=sanitize_metadata(
                        {
                            "baseline_count": len(baselines),
                        }
                    ),
                )

            findings = snapshot.context_json.get("findings", [])
            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.RULES_EVALUATED,
                status=WorkflowStatus.SUCCESS,
                message=f"Rules evaluated for vehicle {vehicle_id} ({len(findings)} findings)",
                vehicle_id=str(vehicle_id),
                metadata=sanitize_metadata(
                    {
                        "findings_count": len(findings),
                    }
                ),
            )

            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.HEALTH_SCORE_CALCULATED,
                status=WorkflowStatus.SUCCESS,
                message=f"Health score calculated: {snapshot.health_score} for vehicle {vehicle_id}",
                vehicle_id=str(vehicle_id),
                metadata=sanitize_metadata(
                    {
                        "score": snapshot.health_score,
                        "status": snapshot.health_status,
                    }
                ),
            )

            if snapshot.confidence is not None:
                await publish_workflow_event(
                    workflow=WorkflowType.HEALTH,
                    stage=WorkflowStage.CONFIDENCE_CALCULATED,
                    status=WorkflowStatus.SUCCESS,
                    message=f"Confidence calculated: {snapshot.confidence:.2f} for vehicle {vehicle_id}",
                    vehicle_id=str(vehicle_id),
                    metadata=sanitize_metadata(
                        {
                            "confidence": snapshot.confidence,
                        }
                    ),
                )

            provisional = snapshot.context_json.get("provisional", False)
            provisional_rating = snapshot.context_json.get("provisional_rating")
            if provisional and provisional_rating:
                await publish_workflow_event(
                    workflow=WorkflowType.HEALTH,
                    stage=WorkflowStage.PROVISIONAL_STATUS_ASSIGNED,
                    status=WorkflowStatus.WARNING,
                    message=f"Provisional status assigned: {provisional_rating} for vehicle {vehicle_id}",
                    vehicle_id=str(vehicle_id),
                    metadata=sanitize_metadata(
                        {
                            "provisional_rating": provisional_rating,
                            "provisional": True,
                        }
                    ),
                )

            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.HEALTH_SNAPSHOT_CREATED,
                status=WorkflowStatus.SUCCESS,
                message=f"Health snapshot created for vehicle {vehicle_id}: {snapshot.health_status}",
                vehicle_id=str(vehicle_id),
                metadata=sanitize_metadata(
                    {
                        "snapshot_id": str(snapshot.id),
                        "health_status": snapshot.health_status,
                        "sample_count": snapshot.sample_count,
                        "confidence": snapshot.confidence,
                        "provisional": provisional,
                        "simulation_run_id": (
                            str(simulation_run_id) if simulation_run_id is not None else None
                        ),
                        "live_policy_met": live_sufficiency.get("policy_met"),
                    }
                ),
            )
        except Exception as exc:
            self._record_failure(result, vehicle_id, "evaluation", exc)
            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.HEALTH_ANALYSIS_STARTED,
                status=WorkflowStatus.ERROR,
                message=f"Health analysis failed for vehicle {vehicle_id}: {exc}",
                vehicle_id=str(vehicle_id),
                metadata=sanitize_metadata(
                    {
                        "error": str(exc),
                        "phase": "evaluation",
                    }
                ),
            )
            return False
        result.evaluated += 1
        # Escalate only on *sufficient, non-provisional* evidence: a collecting
        # session or a stale feed must never re-trigger the diagnosis pipeline
        # from an old snapshot dressed up as a current verdict.
        return should_escalate(snapshot.health_status) and not provisional

    async def _escalate(self, vehicle_id: UUID, result: MonitorPassResult) -> bool:
        """Run the diagnosis for one critical vehicle. Returns False on failure."""
        try:
            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.HEALTH_ANALYSIS_STARTED,
                status=WorkflowStatus.RUNNING,
                message=f"Escalating critical vehicle {vehicle_id} to agent",
                vehicle_id=str(vehicle_id),
            )

            async with self._session_factory() as session:
                await self._agent_service_factory(session).run_critical_event(vehicle_id, user=None)

            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.HEALTH_ANALYSIS_STARTED,
                status=WorkflowStatus.SUCCESS,
                message=f"Critical vehicle {vehicle_id} escalated to agent successfully",
                vehicle_id=str(vehicle_id),
            )
        except Exception as exc:
            self._record_failure(result, vehicle_id, "escalation", exc)
            await publish_workflow_event(
                workflow=WorkflowType.HEALTH,
                stage=WorkflowStage.HEALTH_ANALYSIS_STARTED,
                status=WorkflowStatus.ERROR,
                message=f"Escalation failed for vehicle {vehicle_id}: {exc}",
                vehicle_id=str(vehicle_id),
                metadata=sanitize_metadata(
                    {
                        "error": str(exc),
                        "phase": "escalation",
                    }
                ),
            )
            return False
        return True

    @staticmethod
    def _record_failure(
        result: MonitorPassResult, vehicle_id: UUID, phase: str, exc: Exception
    ) -> None:
        result.failed += 1
        message = f"{vehicle_id}: {type(exc).__name__}: {exc}"
        result.errors.append(message)
        logger.exception("health monitor: %s failed for %s", phase, vehicle_id)


async def run_health_monitor_loop(
    monitor: HealthMonitorService, *, interval_seconds: float
) -> None:
    """Run ``monitor`` once per interval until the task is cancelled.

    The first pass waits one full interval so application startup never blocks
    on analysis. A pass that fails entirely (for example because the database
    went away) is logged and retried on the next tick rather than killing the
    task; per-vehicle failures are already isolated inside ``run_pass``.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await monitor.run_pass()
        except Exception:
            logger.exception("health monitor pass failed")
