from fastapi import APIRouter

from app.api.routes import (
    admin_rag,
    agent,
    auth,
    health,
    rag,
    telemetry,
    users,
    vehicle_health,
    vehicles,
)

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, tags=["Me"])
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
api_router.include_router(
    agent.router,
    prefix="/vehicles/{vehicle_id}/agent",
    tags=["Agent"],
)
api_router.include_router(rag.router, prefix="/rag", tags=["RAG"])
api_router.include_router(admin_rag.router, prefix="/admin", tags=["Admin RAG"])
