from fastapi import APIRouter, Response

from app.core.config import get_settings
from app.core.database import check_database_connection
from app.schemas.health import HealthDBResponse, HealthResponse

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
