"""Historical analytics API: read-only aggregation over persisted telemetry.

Separate from the live current-session view on purpose: this returns bounded
aggregates over an explicit, validated, UTC-aware historical window (1h/24h/
7d/30d/90d presets or a custom range), including per-run boundary segments,
health-snapshot history and time-bucketed sample counts. Ownership is enforced
exactly like every other vehicle-scoped endpoint.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_historical_analytics_service
from app.models.user import User
from app.schemas.historical_analytics import (
    HistoricalAnalyticsParams,
    HistoricalAnalyticsResponse,
)
from app.services.historical_analytics_service import HistoricalAnalyticsService

router = APIRouter()


@router.get(
    "",
    response_model=HistoricalAnalyticsResponse,
    summary="Get historical analytics",
    description=(
        "Read-only analytics over a validated historical window of a vehicle's "
        "persisted telemetry. Ranges: 1h, 24h, 7d, 30d, 90d presets or a "
        "custom UTC-aware range (reversed ranges rejected). Returns per-metric "
        "aggregates, deterministic trends, run-boundary segments, health "
        "snapshot history and time-bucketed counts. Never mutates data."
    ),
)
async def get_historical_analytics(
    vehicle_id: UUID,
    params: Annotated[HistoricalAnalyticsParams, Query()],
    service: Annotated[HistoricalAnalyticsService, Depends(get_historical_analytics_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> HistoricalAnalyticsResponse:
    return await service.get_for_user(
        vehicle_id,
        user,
        range_preset=params.range,
        timezone=params.timezone,
        start_time=params.start_time,
        end_time=params.end_time,
    )
