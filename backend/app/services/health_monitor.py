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
from collections.abc import Callable
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
from app.services.vehicle_health_service import VehicleHealthService

logger = logging.getLogger(__name__)


class HealthEvaluator(Protocol):
    """The slice of VehicleHealthService the monitor depends on."""

    async def analyze_vehicle(
        self, vehicle_id: UUID, window_minutes: float | None = None
    ) -> HealthSnapshot: ...


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
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or get_settings()
        self._health_service_factory = health_service_factory or _default_health_service
        self._agent_service_factory = agent_service_factory or _default_agent_service

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
        return result

    async def _evaluate(self, vehicle_id: UUID, result: MonitorPassResult) -> bool:
        """Analyse one vehicle. Returns False when the analysis failed."""
        try:
            async with self._session_factory() as session:
                snapshot = await self._health_service_factory(session).analyze_vehicle(vehicle_id)
        except Exception as exc:
            self._record_failure(result, vehicle_id, "evaluation", exc)
            return False
        result.evaluated += 1
        return should_escalate(snapshot.health_status)

    async def _escalate(self, vehicle_id: UUID, result: MonitorPassResult) -> bool:
        """Run the diagnosis for one critical vehicle. Returns False on failure."""
        try:
            async with self._session_factory() as session:
                await self._agent_service_factory(session).run_critical_event(vehicle_id, user=None)
        except Exception as exc:
            self._record_failure(result, vehicle_id, "escalation", exc)
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
