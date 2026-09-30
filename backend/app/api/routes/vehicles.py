from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_vehicle_service
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate
from app.services.vehicle_service import VehicleService

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedResponse[VehicleResponse],
    summary="List vehicles",
    description="Paginated list of the caller's vehicles, newest first.",
)
async def list_vehicles(
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[VehicleResponse]:
    vehicles, total = await vehicle_service.list_vehicles_for_user(
        user, page=page, page_size=page_size
    )
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
    description="Register a new vehicle owned by the caller. The VIN must be unique.",
)
async def create_vehicle(
    payload: VehicleCreate,
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleResponse:
    vehicle = await vehicle_service.create_vehicle_for_user(payload, user=user)
    return VehicleResponse.model_validate(vehicle)


@router.get(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    summary="Get vehicle",
    description="Returns a single vehicle by ID, if the caller owns it.",
)
async def get_vehicle(
    vehicle_id: UUID,
    vehicle_service: Annotated[VehicleService, Depends(get_vehicle_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleResponse:
    vehicle = await vehicle_service.get_vehicle_for_user(vehicle_id, user)
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
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleResponse:
    vehicle = await vehicle_service.update_vehicle_for_user(vehicle_id, payload, user)
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
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    await vehicle_service.delete_vehicle_for_user(vehicle_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
