from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.database import get_vehicle_health_service
from app.schemas.common import PaginatedResponse
from app.schemas.vehicle_health import HealthContextResponse, HealthSnapshotItem
from app.services.vehicle_health_service import VehicleHealthService

router = APIRouter()


@router.post(
    "/analyze",
    response_model=HealthContextResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze vehicle health",
    description=(
        "Run a deterministic health analysis over the vehicle's recent "
        "telemetry window, persist a new health snapshot, and return the "
        "generated Vehicle Health Context. Optionally override the analysis "
        "window size with window_minutes."
    ),
)
async def analyze_vehicle_health(
    vehicle_id: UUID,
    vehicle_health_service: Annotated[VehicleHealthService, Depends(get_vehicle_health_service)],
    window_minutes: Annotated[int | None, Query(ge=1, le=1440)] = None,
) -> HealthContextResponse:
    snapshot = await vehicle_health_service.analyze_vehicle(
        vehicle_id, window_minutes=window_minutes
    )
    return HealthContextResponse.model_validate(snapshot.context_json)


@router.get(
    "",
    response_model=HealthContextResponse,
    summary="Get latest health context",
    description="Returns the latest persisted Vehicle Health Context for the vehicle.",
)
async def get_latest_health(
    vehicle_id: UUID,
    vehicle_health_service: Annotated[VehicleHealthService, Depends(get_vehicle_health_service)],
) -> HealthContextResponse:
    snapshot = await vehicle_health_service.get_latest(vehicle_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No health snapshot exists for this vehicle; POST /analyze to generate one",
        )
    return HealthContextResponse.model_validate(snapshot.context_json)


@router.get(
    "/history",
    response_model=PaginatedResponse[HealthSnapshotItem],
    summary="List health history",
    description=(
        "Paginated list of a vehicle's health snapshots, newest first. "
        "Supports optional date filtering with start_time and end_time on generated_at."
    ),
)
async def list_health_history(
    vehicle_id: UUID,
    vehicle_health_service: Annotated[VehicleHealthService, Depends(get_vehicle_health_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    start_time: Annotated[
        datetime | None, Query(description="Inclusive lower bound (ISO 8601)")
    ] = None,
    end_time: Annotated[
        datetime | None, Query(description="Inclusive upper bound (ISO 8601)")
    ] = None,
) -> PaginatedResponse[HealthSnapshotItem]:
    snapshots, total = await vehicle_health_service.list_history(
        vehicle_id,
        page=page,
        page_size=page_size,
        start_time=start_time,
        end_time=end_time,
    )
    return PaginatedResponse(
        items=[HealthSnapshotItem.model_validate(s) for s in snapshots],
        page=page,
        page_size=page_size,
        total=total,
    )
