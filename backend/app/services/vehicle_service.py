from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.vehicle import Vehicle
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate, VehicleUpdate


class VehicleService:
    """Business logic for vehicle management. Commits at the operation boundary."""

    def __init__(self, session: AsyncSession, repository: VehicleRepository) -> None:
        self._session = session
        self._repository = repository

    async def get_vehicle(self, vehicle_id: UUID) -> Vehicle:
        vehicle = await self._repository.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle")
        return vehicle

    async def get_vehicle_by_vin(self, vin: str) -> Vehicle | None:
        return await self._repository.get_by_vin(vin)

    async def list_vehicles(self, *, page: int, page_size: int) -> tuple[list[Vehicle], int]:
        return await self._repository.list(page=page, page_size=page_size)

    async def create_vehicle(self, data: VehicleCreate) -> Vehicle:
        vehicle = Vehicle(**data.model_dump())
        created = await self._repository.create(vehicle)
        await self._session.commit()
        return created

    async def update_vehicle(self, vehicle_id: UUID, data: VehicleUpdate) -> Vehicle:
        vehicle = await self.get_vehicle(vehicle_id)
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return vehicle
        updated = await self._repository.update(vehicle, fields)
        await self._session.commit()
        return updated

    async def delete_vehicle(self, vehicle_id: UUID) -> None:
        vehicle = await self.get_vehicle(vehicle_id)
        await self._repository.delete(vehicle)
        await self._session.commit()
