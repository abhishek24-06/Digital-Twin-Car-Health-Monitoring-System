"""Fleet overview API (read-only).

One ownership-scoped request that backs the dashboard: every vehicle the caller
can access, each with its simulator state, telemetry freshness, latest stored
health assessment and active-alert tally, plus the fleet KPI totals.

This is deliberately *not* a per-vehicle endpoint in disguise -- it exists so the
dashboard never fires one request per vehicle. It reuses the simulation
supervisor and the telemetry/snapshot/alert repositories; it never scores a
vehicle, never mutates anything, and never fabricates a value that was not
stored.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db, get_vehicle_service
from app.models.user import User
from app.schemas.fleet import FleetOverviewResponse
from app.services.fleet_overview import build_fleet_overview, load_fleet_vehicles
from app.services.simulation_manager import SimulationManager, get_simulation_manager
from app.services.subscriber_manager import SubscriberSupervisor, get_subscriber_supervisor
from app.services.vehicle_service import VehicleService

router = APIRouter()


@router.get(
    "/overview",
    response_model=FleetOverviewResponse,
    summary="Fleet overview",
    description=(
        "Read-only fleet snapshot for the caller's vehicles (ownership or admin "
        "visibility, exactly like the vehicles list). Each row reports the "
        "reconciled simulator state, telemetry freshness, the latest stored "
        "health assessment (with its own timestamp and provisional flag) and the "
        "active-alert tally. Fleet totals are derived from the same signals."
    ),
)
async def get_fleet_overview(
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
    manager: Annotated[SimulationManager, Depends(get_simulation_manager)],
    subscriber: Annotated[SubscriberSupervisor, Depends(get_subscriber_supervisor)],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> FleetOverviewResponse:
    vehicles = await load_fleet_vehicles(vehicle_service, user)
    return await build_fleet_overview(session, vehicles, manager, subscriber)
