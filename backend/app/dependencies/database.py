from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.telemetry_service import TelemetryService
from app.services.vehicle_service import VehicleService


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield an async session, guaranteeing it is closed when the request ends."""
    async with get_session_factory()() as session:
        yield session


def get_vehicle_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> VehicleRepository:
    return VehicleRepository(session)


def get_vehicle_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> VehicleService:
    return VehicleService(session=session, repository=VehicleRepository(session))


def get_telemetry_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TelemetryService:
    return TelemetryService(
        session=session,
        repository=TelemetryRepository(session),
        vehicle_repository=VehicleRepository(session),
    )
