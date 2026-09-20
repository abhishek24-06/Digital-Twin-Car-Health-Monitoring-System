from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.vehicle import Vehicle


class VehicleRepository:
    """Data access for the Vehicle entity."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, vehicle_id: UUID) -> Vehicle | None:
        statement = select(Vehicle).where(Vehicle.id == vehicle_id)
        return await self._session.scalar(statement)

    async def get_by_vin(self, vin: str) -> Vehicle | None:
        statement = select(Vehicle).where(Vehicle.vin == vin)
        return await self._session.scalar(statement)

    async def list(self, *, page: int, page_size: int) -> tuple[list[Vehicle], int]:
        total = await self._session.scalar(select(func.count()).select_from(Vehicle))
        statement = (
            select(Vehicle)
            .order_by(Vehicle.created_at.desc(), Vehicle.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.scalars(statement)
        return list(result.all()), int(total or 0)

    async def create(self, vehicle: Vehicle) -> Vehicle:
        try:
            self._session.add(vehicle)
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError("A vehicle with this VIN already exists") from exc
        await self._session.refresh(vehicle)
        return vehicle

    async def update(self, vehicle: Vehicle, fields: dict[str, object]) -> Vehicle:
        try:
            for key, value in fields.items():
                setattr(vehicle, key, value)
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError("A vehicle with this VIN already exists") from exc
        await self._session.refresh(vehicle)
        return vehicle

    async def delete(self, vehicle: Vehicle) -> None:
        await self._session.delete(vehicle)
        await self._session.flush()
