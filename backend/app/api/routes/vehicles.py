from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.database import get_vehicle_service
from app.schemas.common import PaginatedResponse
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate
from app.services.vehicle_service import VehicleService

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedResponse[VehicleResponse],
    summary="List vehicles",
    description="Paginated list of vehicles, newest first. Does not load telemetry.",
)
async def list_vehicles(
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[VehicleResponse]:
    vehicles, total = await vehicle_service.list_vehicles(page=page, page_size=page_size)
    return PaginatedResponse(
        items=[VehicleResponse.model_validate(v) for v in vehicles],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create vehicle",
    description="Register a new vehicle. The VIN must be unique.",
)
async def create_vehicle(
    payload: VehicleCreate,
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
) -> VehicleResponse:
    vehicle = await vehicle_service.create_vehicle(payload)
    return VehicleResponse.model_validate(vehicle)


@router.get(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    summary="Get vehicle",
    description="Returns a single vehicle by ID.",
)
async def get_vehicle(
    vehicle_id: UUID,
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
) -> VehicleResponse:
    vehicle = await vehicle_service.get_vehicle(vehicle_id)
    return VehicleResponse.model_validate(vehicle)


@router.patch(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    summary="Update vehicle",
    description="Updates mutable vehicle metadata. The VIN is immutable.",
)
async def update_vehicle(
    vehicle_id: UUID,
    payload: VehicleUpdate,
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
) -> VehicleResponse:
    vehicle = await vehicle_service.update_vehicle(vehicle_id, payload)
    return VehicleResponse.model_validate(vehicle)


@router.delete(
    "/{vehicle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete vehicle",
    description="Deletes the vehicle and cascades to its telemetry records.",
)
async def delete_vehicle(
    vehicle_id: UUID,
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
) -> Response:
    await vehicle_service.delete_vehicle(vehicle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
