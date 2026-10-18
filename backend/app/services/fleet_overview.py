"""Fleet overview composition (read-only).

Turns the caller's vehicles plus four batched queries into the single snapshot
the dashboard renders. Every value is traceable to a real stored signal; nothing
is defaulted. The two classification rules live here so they are defined (and
tested) in exactly one place:

``telemetry_freshness``
    The newest persisted telemetry ``timestamp`` is compared to
    :data:`app.services.telemetry_freshness.STALE_AFTER_SECONDS`. ``no_data``
    means the vehicle never persisted a sample; ``unknown`` is reserved for an
    uninterpretable timestamp.

``requires_attention``
    True when the vehicle has at least one *active* (open or acknowledged)
    warning/critical alert -- the current, mutable signal -- or when a
    **fresh** stored assessment rates the vehicle ``attention``/``critical``.
    The freshness gate is what stops an old assessment from being counted as a
    present-day problem. ``limited_data`` assessments use their
    ``provisional_rating`` so a provisional ``critical`` still counts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.intelligence.models import RATING_STATUSES
from app.models.health_snapshot import HealthSnapshot
from app.models.user import User
from app.models.vehicle import Vehicle
from app.repositories.alert_repository import AlertRepository
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas.fleet import (
    FleetAssessmentSummary,
    FleetOverviewResponse,
    FleetTotals,
    FleetVehicleSummary,
    TelemetryFreshness,
)
from app.services.simulation_manager import SimulationManager
from app.services.simulation_state import derive_simulation_state
from app.services.subscriber_manager import SubscriberSupervisor
from app.services.telemetry_freshness import (
    STALE_AFTER_SECONDS,
    snapshot_stale_after_seconds,
)
from app.services.vehicle_service import VehicleService

#: Page size for the ownership-scoped vehicle listing. The overview fetches every
#: page so a large fleet is never silently truncated; the hard cap keeps a
#: pathological account from unbounded loops.
_PAGE_SIZE = 500
_MAX_PAGES = 20

#: Simulator lifecycle states that count as an active simulation.
_ACTIVE_SIMULATION_STATES = frozenset({"starting", "running", "stopping"})


def _as_utc(value: datetime) -> datetime:
    """Attach UTC to a naive timestamp so age maths is timezone-safe."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _age_seconds(value: datetime, now: datetime) -> float:
    return (now - _as_utc(value)).total_seconds()


def _classify_telemetry(last_telemetry_at: datetime | None, now: datetime) -> TelemetryFreshness:
    """Freshness label for the newest persisted telemetry timestamp."""
    if last_telemetry_at is None:
        return "no_data"
    try:
        age = _age_seconds(last_telemetry_at, now)
    except (TypeError, ValueError, OverflowError):
        return "unknown"
    return "recent" if age <= STALE_AFTER_SECONDS else "stale"


def _assessment_summary(snapshot: HealthSnapshot) -> FleetAssessmentSummary:
    context = snapshot.context_json or {}
    provisional = bool(context.get("provisional", False))
    return FleetAssessmentSummary(
        health_status=snapshot.health_status,
        provisional_rating=context.get("provisional_rating"),
        health_score=snapshot.health_score,
        confidence=snapshot.confidence,
        generated_at=snapshot.generated_at,
        provisional=provisional,
        data_sufficiency=context.get("data_sufficiency"),
        analysis_scope=context.get("analysis_scope"),
        sample_count=snapshot.sample_count,
    )


def _effective_rating(assessment: FleetAssessmentSummary) -> str:
    """The vehicle-condition rating behind an assessment.

    A limited-data assessment reports a data-state ``health_status`` (e.g.
    ``limited_data``) and carries the real rating in ``provisional_rating``; fall
    back to it so a provisional ``critical`` is never read as neutral.
    """
    if assessment.provisional and assessment.provisional_rating in RATING_STATUSES:
        return assessment.provisional_rating
    return assessment.health_status


async def load_fleet_vehicles(vehicle_service: VehicleService, user: User) -> list[Vehicle]:
    """Every vehicle the caller may access, paged to completion.

    A fleet view must not silently drop vehicles past the first page, so pages
    are fetched until exhausted; ``_MAX_PAGES`` bounds a pathological account.
    """
    vehicles: list[Vehicle] = []
    page = 1
    while page <= _MAX_PAGES:
        batch, total = await vehicle_service.list_vehicles_for_user(
            user, page=page, page_size=_PAGE_SIZE
        )
        vehicles.extend(batch)
        if not batch or len(vehicles) >= total:
            break
        page += 1
    return vehicles


async def build_fleet_overview(
    session: AsyncSession,
    vehicles: list[Vehicle],
    manager: SimulationManager,
    subscriber: SubscriberSupervisor,
    *,
    now: datetime | None = None,
) -> FleetOverviewResponse:
    """Compose the fleet snapshot for an already ownership-scoped vehicle list.

    Read-only: it issues four batched queries (telemetry timestamps, latest
    snapshots, active-alert tallies) plus the in-process supervisor reads, never
    one query per vehicle.
    """
    now = now or datetime.now(UTC)
    settings = get_settings()
    assessment_stale_after = snapshot_stale_after_seconds(
        monitor_min_seconds=settings.health_monitor_min_seconds,
        monitor_interval_seconds=settings.health_monitor_interval_seconds,
    )

    vehicle_ids = [vehicle.id for vehicle in vehicles]
    latest_telemetry = await TelemetryRepository(session).get_latest_timestamps(vehicle_ids)
    latest_snapshots = await HealthSnapshotRepository(session).get_latest_by_vehicles(vehicle_ids)
    alert_counts = await AlertRepository(session).count_active_by_vehicles(vehicle_ids)
    statuses = await manager.statuses_for(vehicle_ids)
    subscriber_running = (await subscriber.health()).running

    summaries: list[FleetVehicleSummary] = []
    for vehicle in vehicles:
        simulation = statuses[vehicle.id]
        last_telemetry_at = latest_telemetry.get(vehicle.id)
        simulation_state, simulation_error = derive_simulation_state(
            simulation, last_telemetry_at, subscriber_running, now=now
        )

        snapshot = latest_snapshots.get(vehicle.id)
        assessment = _assessment_summary(snapshot) if snapshot is not None else None
        if snapshot is None:
            assessment_freshness = "none"
        elif _age_seconds(snapshot.generated_at, now) <= assessment_stale_after:
            assessment_freshness = "fresh"
        else:
            assessment_freshness = "stale"

        counts = alert_counts.get(vehicle.id)
        open_alerts = counts.active if counts else 0
        critical_open = counts.critical if counts else 0
        warning_open = counts.warning if counts else 0

        requires_attention = open_alerts > 0 or (
            assessment is not None
            and assessment_freshness == "fresh"
            and _effective_rating(assessment) in ("attention", "critical")
        )

        summaries.append(
            FleetVehicleSummary(
                vehicle_id=vehicle.id,
                vin=vehicle.vin,
                make=vehicle.make,
                model=vehicle.model,
                year=vehicle.year,
                engine_type=vehicle.engine_type,
                status=vehicle.status,
                simulation_state=simulation_state,
                simulation_scenario=simulation.scenario,
                simulation_started_at=simulation.started_at,
                simulation_error=simulation_error,
                last_telemetry_at=last_telemetry_at,
                telemetry_freshness=_classify_telemetry(last_telemetry_at, now),
                assessment=assessment,
                assessment_freshness=assessment_freshness,
                open_alerts=open_alerts,
                critical_open_alerts=critical_open,
                warning_open_alerts=warning_open,
                requires_attention=requires_attention,
            )
        )

    totals = FleetTotals(
        vehicles=len(summaries),
        vehicles_with_recent_telemetry=sum(
            1 for item in summaries if item.telemetry_freshness == "recent"
        ),
        vehicles_requiring_attention=sum(1 for item in summaries if item.requires_attention),
        vehicles_with_open_alerts=sum(1 for item in summaries if item.open_alerts > 0),
        active_simulations=sum(
            1 for item in summaries if item.simulation_state in _ACTIVE_SIMULATION_STATES
        ),
        open_alerts=sum(item.open_alerts for item in summaries),
        critical_open_alerts=sum(item.critical_open_alerts for item in summaries),
    )

    return FleetOverviewResponse(
        generated_at=now,
        telemetry_stale_after_seconds=STALE_AFTER_SECONDS,
        assessment_stale_after_seconds=assessment_stale_after,
        totals=totals,
        vehicles=summaries,
    )
