from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.user import ROLE_ADMIN, User
from app.models.vehicle import Vehicle
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate, VehicleUpdate


class VehicleService:
    """Business logic for vehicle management. Commits at the operation boundary.

    Ownership-aware variants (``*_for_user``) enforce membership at the service
    layer: a non-admin caller may only read/update/delete vehicles whose
    ``owner_user_id`` matches their own id. Admin callers bypass membership.
    """

    def __init__(self, session: AsyncSession, repository: VehicleRepository) -> None:
        self._session = session
        self._repository = repository

    async def get_vehicle(self, vehicle_id: UUID) -> Vehicle:
        vehicle = await self._repository.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle")
        return vehicle

    async def get_vehicle_for_user(self, vehicle_id: UUID, user: User) -> Vehicle:
        if user.role == ROLE_ADMIN:
            return await self.get_vehicle(vehicle_id)
        vehicle = await self._repository.get_by_id_and_owner(vehicle_id, user.id)
        if vehicle is None:
            # Existing public endpoints surface a missing/unowned resource the
            # same way: 404, never leaking another user's vehicle exists.
            raise NotFoundError("Vehicle")
        return vehicle

    async def get_vehicle_by_vin(self, vin: str) -> Vehicle | None:
        return await self._repository.get_by_vin(vin)

    async def list_vehicles(self, *, page: int, page_size: int) -> tuple[list[Vehicle], int]:
        return await self._repository.list(page=page, page_size=page_size)

    async def list_vehicles_for_user(
        self, user: User, *, page: int, page_size: int
    ) -> tuple[list[Vehicle], int]:
        if user.role == ROLE_ADMIN:
            return await self._repository.list(page=page, page_size=page_size)
        return await self._repository.list_by_owner(user.id, page=page, page_size=page_size)

    async def create_vehicle(
        self, data: VehicleCreate, *, owner_user_id: UUID | None = None
    ) -> Vehicle:
        vehicle = Vehicle(**data.model_dump(), owner_user_id=owner_user_id)
        created = await self._repository.create(vehicle)
        await self._session.commit()
        return created

    async def create_vehicle_for_user(self, data: VehicleCreate, *, user: User) -> Vehicle:
        """User-scoped create: the vehicle is attributed to ``user``."""
        return await self.create_vehicle(data, owner_user_id=user.id)

    async def _update_owned(self, vehicle: Vehicle, data: VehicleUpdate) -> Vehicle:
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return vehicle
        updated = await self._repository.update(vehicle, fields)
        await self._session.commit()
        return updated

    async def update_vehicle(self, vehicle_id: UUID, data: VehicleUpdate) -> Vehicle:
        """Trusted internal path (scripts/tests); HTTP routes use ``_for_user``."""
        vehicle = await self.get_vehicle(vehicle_id)
        return await self._update_owned(vehicle, data)

    async def delete_vehicle(self, vehicle_id: UUID) -> None:
        """Trusted internal path (scripts/tests); HTTP routes use ``_for_user``."""
        vehicle = await self.get_vehicle(vehicle_id)
        await self._repository.delete(vehicle)
        await self._session.commit()

    async def update_vehicle_for_user(
        self, vehicle_id: UUID, data: VehicleUpdate, user: User
    ) -> Vehicle:
        vehicle = await self.get_vehicle_for_user(vehicle_id, user)
        return await self._update_owned(vehicle, data)

    async def delete_vehicle_for_user(self, vehicle_id: UUID, user: User) -> None:
        vehicle = await self.get_vehicle_for_user(vehicle_id, user)
        await self._repository.delete(vehicle)
        await self._session.commit()
