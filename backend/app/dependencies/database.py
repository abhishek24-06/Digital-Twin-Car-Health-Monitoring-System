from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.service import AgentService
from app.core.database import get_session_factory
from app.rag.admin_documents import AdminRagDocumentService
from app.rag.rag_service import RAGService
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.auth_service import AuthService, UserService
from app.services.telemetry_service import TelemetryService
from app.services.vehicle_health_service import VehicleHealthService
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


def get_vehicle_health_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> VehicleHealthService:
    return VehicleHealthService(
        session=session,
        vehicle_repository=VehicleRepository(session),
        telemetry_repository=TelemetryRepository(session),
        health_repository=HealthSnapshotRepository(session),
    )


def get_agent_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AgentService:
    return AgentService(session)


def get_rag_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RAGService:
    """Construct the request-scoped RAGService (lazy — no weights at build)."""
    return RAGService()


def get_admin_rag_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AdminRagDocumentService:
    """Request-scoped admin RAG document management service."""
    return AdminRagDocumentService(session)


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthService:
    return AuthService(session)


def get_user_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserService:
    return UserService(session)
