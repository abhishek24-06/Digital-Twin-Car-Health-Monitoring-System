from fastapi import APIRouter

from app.api.routes import health, telemetry, vehicle_health, vehicles

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(vehicles.router, prefix="/vehicles", tags=["Vehicles"])
api_router.include_router(
    telemetry.router,
    prefix="/vehicles/{vehicle_id}/telemetry",
    tags=["Telemetry"],
)
api_router.include_router(
    vehicle_health.router,
    prefix="/vehicles/{vehicle_id}/health",
    tags=["Vehicle Health"],
)
