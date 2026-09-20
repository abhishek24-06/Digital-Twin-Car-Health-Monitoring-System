from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.database import get_telemetry_service
from app.schemas.common import PaginatedResponse
from app.schemas.telemetry import TelemetryCreate, TelemetryResponse
from app.services.telemetry_service import TelemetryService

router = APIRouter()


@router.post(
    "",
    response_model=TelemetryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create telemetry",
    description="Store a single telemetry sample for a vehicle.",
)
async def create_telemetry(
    vehicle_id: UUID,
    payload: TelemetryCreate,
    telemetry_service: Annotated[TelemetryService, Depends(get_telemetry_service)],
) -> TelemetryResponse:
    record = await telemetry_service.create_telemetry(vehicle_id, payload)
    return TelemetryResponse.model_validate(record)


@router.get(
    "",
    response_model=PaginatedResponse[TelemetryResponse],
    summary="List telemetry",
    description=(
        "Paginated list of a vehicle's telemetry, newest first. "
        "Supports optional time-range filtering with start_time and end_time."
    ),
)
async def list_telemetry(
    vehicle_id: UUID,
    telemetry_service: Annotated[TelemetryService, Depends(get_telemetry_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    start_time: Annotated[
        datetime | None, Query(description="Inclusive lower bound (ISO 8601)")
    ] = None,
    end_time: Annotated[
        datetime | None, Query(description="Inclusive upper bound (ISO 8601)")
    ] = None,
) -> PaginatedResponse[TelemetryResponse]:
    records, total = await telemetry_service.list_vehicle_telemetry(
        vehicle_id,
        page=page,
        page_size=page_size,
        start_time=start_time,
        end_time=end_time,
    )
    return PaginatedResponse(
        items=[TelemetryResponse.model_validate(r) for r in records],
        page=page,
        page_size=page_size,
        total=total,
    )
