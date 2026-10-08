"""Simulation Control API: start/stop/restart/status per vehicle.

The simulator manager supervises a real ``simulator.main`` subprocess per
vehicle on the host machine; these routes expose that lifecycle to the UI.
Every route enforces vehicle ownership (or admin bypass) exactly like the
existing telemetry/health routes, and never leaks the process details to the
caller.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db, get_vehicle_service
from app.models.user import User
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.common import PaginatedResponse
from app.schemas.simulation import SimulationStartRequest, SimulationState, SimulationStatusResponse
from app.services.simulation_manager import (
    SimulationManager,
    SimulationStatus,
    get_simulation_manager,
)
from app.services.subscriber_manager import SubscriberSupervisor, get_subscriber_supervisor
from app.services.vehicle_access import ensure_vehicle_access
from app.services.vehicle_service import VehicleService

vehicle_simulation_router = APIRouter()
simulations_router = APIRouter()

# A freshly spawned simulator gets a warm-up window before its missing feed is
# treated as a fault; afterwards any running process whose newest persisted row
# is older than this is "degraded" rather than healthily "running".
_STARTUP_BUFFER_SECONDS = 25.0
_STALE_AFTER_SECONDS = 30.0


def _to_response(
    simulation: SimulationStatus,
    last_telemetry_at: datetime | None,
    *,
    state: SimulationState,
    error: str | None,
) -> SimulationStatusResponse:
    return SimulationStatusResponse(
        vehicle_id=simulation.vehicle_id,
        status=state,
        scenario=simulation.scenario,
        interval_seconds=simulation.interval_seconds,
        seed=simulation.seed,
        started_at=simulation.started_at,
        error=error,
        last_telemetry_at=last_telemetry_at,
    )


async def _last_telemetry_at(session: AsyncSession, vehicle_id: UUID) -> datetime | None:
    return (await TelemetryRepository(session).get_latest_timestamps([vehicle_id])).get(vehicle_id)


def _derive_state(
    simulation: SimulationStatus,
    last_telemetry_at: datetime | None,
    subscriber_running: bool,
    *,
    now: datetime | None = None,
) -> tuple[SimulationState, str | None]:
    """Truthful status for a vehicle.

    The manager's lifecycle state is reconciled against the pipeline: a
    started process that cannot possibly be delivering telemetry (subscriber
    offline, or no row in the database while the simulator has been up for
    longer than the warm-up window) is reported as ``degraded`` with a
    self-explanatory reason, never as a hollow "running".
    """
    lifecycle = simulation.status
    if lifecycle not in ("starting", "running"):
        return lifecycle, simulation.error
    if not subscriber_running:
        return (
            "degraded",
            "Telemetry ingestion is offline: the backend subscriber is not running, "
            "so simulator output is not reaching the database.",
        )
    if lifecycle == "running" and _telemetry_is_stale(simulation, last_telemetry_at, now=now):
        return "degraded", _stale_reason(last_telemetry_at)
    return lifecycle, simulation.error


def _telemetry_is_stale(
    simulation: SimulationStatus,
    last_telemetry_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    if simulation.started_at is not None:
        uptime = (now - simulation.started_at).total_seconds()
        if uptime < _STARTUP_BUFFER_SECONDS:
            return False
    if last_telemetry_at is None:
        return True
    return (now - last_telemetry_at).total_seconds() > _STALE_AFTER_SECONDS


def _stale_reason(last_telemetry_at: datetime | None) -> str:
    if last_telemetry_at is None:
        return (
            "Simulator is running but no telemetry has reached the database yet. "
            "Check the MQTT broker and the backend subscriber."
        )
    return (
        f"Simulator is running but the newest telemetry is from "
        f"{last_telemetry_at.isoformat()} -- the feed has gone stale. Check the MQTT "
        "broker and the backend subscriber."
    )


@vehicle_simulation_router.post(
    "",
    response_model=SimulationStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start simulation",
    description=(
        "Start a simulator for a vehicle the caller owns (or may access as an "
        "admin). Returns 409 when a simulation is already active for the "
        "vehicle. Scenario names match the simulator's supported set."
    ),
)
async def start_simulation(
    vehicle_id: UUID,
    payload: SimulationStartRequest,
    manager: Annotated[SimulationManager, Depends(get_simulation_manager)],
    subscriber: Annotated[SubscriberSupervisor, Depends(get_subscriber_supervisor)],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SimulationStatusResponse:
    await ensure_vehicle_access(VehicleRepository(session), vehicle_id, user)
    simulation = await manager.start(
        vehicle_id, payload.scenario, payload.interval_seconds, payload.seed
    )
    last_telemetry_at = await _last_telemetry_at(session, vehicle_id)
    subscriber_running = (await subscriber.health()).running
    state, error = _derive_state(simulation, last_telemetry_at, subscriber_running)
    return _to_response(simulation, last_telemetry_at, state=state, error=error)


@vehicle_simulation_router.get(
    "",
    response_model=SimulationStatusResponse,
    summary="Get simulation status",
    description=(
        "Current simulator state for a vehicle. A vehicle with no simulator "
        "reports a default 'stopped' status so the UI does not need a special "
        "empty case."
    ),
)
async def get_simulation_status(
    vehicle_id: UUID,
    manager: Annotated[SimulationManager, Depends(get_simulation_manager)],
    subscriber: Annotated[SubscriberSupervisor, Depends(get_subscriber_supervisor)],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SimulationStatusResponse:
    await ensure_vehicle_access(VehicleRepository(session), vehicle_id, user)
    simulation = await manager.get_status(vehicle_id)
    last_telemetry_at = await _last_telemetry_at(session, vehicle_id)
    subscriber_running = (await subscriber.health()).running
    state, error = _derive_state(simulation, last_telemetry_at, subscriber_running)
    return _to_response(simulation, last_telemetry_at, state=state, error=error)


@vehicle_simulation_router.delete(
    "",
    response_model=SimulationStatusResponse,
    summary="Stop simulation",
    description=(
        "Gracefully stop a vehicle's simulator. Idempotent: stopping a "
        "vehicle without an active simulator returns the stopped status."
    ),
)
async def stop_simulation(
    vehicle_id: UUID,
    manager: Annotated[SimulationManager, Depends(get_simulation_manager)],
    subscriber: Annotated[SubscriberSupervisor, Depends(get_subscriber_supervisor)],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SimulationStatusResponse:
    await ensure_vehicle_access(VehicleRepository(session), vehicle_id, user)
    simulation = await manager.stop(vehicle_id)
    last_telemetry_at = await _last_telemetry_at(session, vehicle_id)
    subscriber_running = (await subscriber.health()).running
    state, error = _derive_state(simulation, last_telemetry_at, subscriber_running)
    return _to_response(simulation, last_telemetry_at, state=state, error=error)


@vehicle_simulation_router.post(
    "/restart",
    response_model=SimulationStatusResponse,
    summary="Restart simulation",
    description=(
        "Stop any active simulator for the vehicle and start a fresh one with "
        "the supplied configuration (for example, to switch scenario)."
    ),
)
async def restart_simulation(
    vehicle_id: UUID,
    payload: SimulationStartRequest,
    manager: Annotated[SimulationManager, Depends(get_simulation_manager)],
    subscriber: Annotated[SubscriberSupervisor, Depends(get_subscriber_supervisor)],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SimulationStatusResponse:
    await ensure_vehicle_access(VehicleRepository(session), vehicle_id, user)
    simulation = await manager.restart(
        vehicle_id, payload.scenario, payload.interval_seconds, payload.seed
    )
    last_telemetry_at = await _last_telemetry_at(session, vehicle_id)
    subscriber_running = (await subscriber.health()).running
    state, error = _derive_state(simulation, last_telemetry_at, subscriber_running)
    return _to_response(simulation, last_telemetry_at, state=state, error=error)


@simulations_router.get(
    "",
    response_model=PaginatedResponse[SimulationStatusResponse],
    summary="List simulation statuses",
    description=(
        "Simulation status for every vehicle the caller can access, newest "
        "vehicles first. Include 'last_telemetry_at' so the UI can flag a "
        "running simulator that is not streaming (broker/subscriber down)."
    ),
)
async def list_simulations(
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
    manager: Annotated[SimulationManager, Depends(get_simulation_manager)],
    subscriber: Annotated[SubscriberSupervisor, Depends(get_subscriber_supervisor)],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> PaginatedResponse[SimulationStatusResponse]:
    vehicles, total = await vehicle_service.list_vehicles_for_user(
        user, page=page, page_size=page_size
    )
    vehicle_ids = [vehicle.id for vehicle in vehicles]
    statuses = await manager.statuses_for(vehicle_ids)
    latest = await TelemetryRepository(session).get_latest_timestamps(vehicle_ids)
    subscriber_running = (await subscriber.health()).running
    items = []
    for vehicle in vehicles:
        simulation = statuses[vehicle.id]
        last = latest.get(vehicle.id)
        state, error = _derive_state(simulation, last, subscriber_running)
        items.append(_to_response(simulation, last, state=state, error=error))
    return PaginatedResponse(items=items, page=page, page_size=page_size, total=total)
