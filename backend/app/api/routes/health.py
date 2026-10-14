from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import check_database_connection
from app.dependencies.auth import require_admin
from app.dependencies.database import get_db
from app.models.user import User
from app.schemas.health import (
    DeploymentStatusResponse,
    HealthDBResponse,
    HealthResponse,
)
from app.services.deployment_status import (
    build_diagnostics,
    detect_features,
    read_database_schema_revision,
)

router = APIRouter()

settings = get_settings()
SERVICE_NAME = "digital-twin-api"


@router.get(
    "",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service liveness information. Does not touch the database.",
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@router.get(
    "/db",
    response_model=HealthDBResponse,
    summary="Database health check",
    description="Runs a lightweight SELECT 1 to verify database reachability.",
    responses={503: {"description": "Database unavailable"}},
)
async def database_health(response: Response) -> HealthDBResponse:
    database_up = await check_database_connection()
    if not database_up:
        response.status_code = 503
    return HealthDBResponse(
        status="ok" if database_up else "degraded",
        service=SERVICE_NAME,
        database="ok" if database_up else "unavailable",
    )


@router.get(
    "/deployment",
    response_model=DeploymentStatusResponse,
    summary="Deployment verification status",
    description=(
        "Admin-only, read-only verification that the running build matches the "
        "database schema and exposes the expected feature routes. Compares the "
        "database's recorded Alembic revision with EXPECTED_SCHEMA_REVISION. It "
        "never applies a migration and never exposes secrets or connection "
        "strings."
    ),
    responses={403: {"description": "Admin privileges required"}},
)
async def deployment_status(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DeploymentStatusResponse:
    settings = get_settings()
    database_reachable = await check_database_connection()
    actual = await read_database_schema_revision(session) if database_reachable else None
    expected = settings.expected_schema_revision

    migration_in_sync: bool | None = None
    if database_reachable and expected is not None:
        migration_in_sync = actual == expected

    return DeploymentStatusResponse(
        service=SERVICE_NAME,
        app_version=settings.app_version,
        build_id=settings.build_id,
        environment=settings.app_env,
        database_reachable=database_reachable,
        expected_schema_revision=expected,
        database_schema_revision=actual,
        migration_in_sync=migration_in_sync,
        features=detect_features(request.app, settings),
        diagnostics=build_diagnostics(
            database_reachable=database_reachable,
            actual=actual,
            expected=expected,
        ),
    )
