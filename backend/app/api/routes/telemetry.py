import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.dependencies.auth import get_current_user, get_current_user_stream
from app.dependencies.database import get_telemetry_service
from app.models.user import User
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.common import PaginatedResponse
from app.schemas.telemetry import TelemetryCreate, TelemetryResponse
from app.services.telemetry_service import TelemetryService
from app.services.vehicle_access import ensure_vehicle_access

router = APIRouter()


@router.post(
    "",
    response_model=TelemetryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create telemetry",
    description="Store a single telemetry sample for a vehicle the caller owns.",
)
async def create_telemetry(
    vehicle_id: UUID,
    payload: TelemetryCreate,
    telemetry_service: Annotated[TelemetryService, Depends(get_telemetry_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> TelemetryResponse:
    record = await telemetry_service.create_telemetry_for_user(vehicle_id, payload, user)
    return TelemetryResponse.model_validate(record)


@router.get(
    "",
    response_model=PaginatedResponse[TelemetryResponse],
    summary="List telemetry",
    description=(
        "Paginated list of a vehicle's telemetry, newest first. "
        "Supports optional time-range filtering with start_time and end_time."
    ),
)
async def list_telemetry(
    vehicle_id: UUID,
    telemetry_service: Annotated[TelemetryService, Depends(get_telemetry_service)],
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    start_time: Annotated[
        datetime | None, Query(description="Inclusive lower bound (ISO 8601)")
    ] = None,
    end_time: Annotated[
        datetime | None, Query(description="Inclusive upper bound (ISO 8601)")
    ] = None,
) -> PaginatedResponse[TelemetryResponse]:
    records, total = await telemetry_service.list_vehicle_telemetry_for_user(
        vehicle_id,
        user,
        page=page,
        page_size=page_size,
        start_time=start_time,
        end_time=end_time,
    )
    return PaginatedResponse(
        items=[TelemetryResponse.model_validate(r) for r in records],
        page=page,
        page_size=page_size,
        total=total,
    )


async def _read_stream(
    vehicle_id: UUID,
    *,
    interval_seconds: float,
) -> AsyncIterator[str]:
    """Poll for telemetry newer than the connection cursor and emit SSE frames.

    Each data frame is a JSON document with ``timestamp`` (the newest sample in
    the batch), ``events`` (the telemetry records received since the last
    event), and ``server_time``. Idle polls emit a heartbeat comment so clients
    and intermediaries can tell a healthy but quiet stream from a dead one.

    Every poll uses its own short-lived session so a stream never pins a pooled
    connection (or an open transaction) for its lifetime -- the same reason the
    workflow SSE route resolves auth without the request-scoped DB session.
    """
    cursor = datetime.now(UTC)
    while True:
        session = get_session_factory()()
        try:
            records = await TelemetryRepository(session).list_since(
                vehicle_id, after=cursor, limit=200
            )
        finally:
            await session.close()
        now = datetime.now(UTC)
        if records:
            cursor = records[-1].timestamp
            events = [TelemetryResponse.model_validate(r).model_dump(mode="json") for r in records]
            payload = {
                "timestamp": events[-1]["timestamp"],
                "events": events,
                "server_time": now.isoformat(),
            }
            yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        else:
            yield ": ping\n\n"
        await asyncio.sleep(interval_seconds)


@router.get(
    "/stream",
    summary="Stream live telemetry",
    description=(
        "Server-sent events stream of a vehicle's new telemetry (auth required, "
        "caller must own the vehicle or be an admin). Each data event is a JSON "
        "document with 'timestamp' (newest sample in the batch), 'events' (the "
        "telemetry records received since the last event), and 'server_time'. "
        "Heartbeat comments are emitted while idle. The stream closes when the "
        "client disconnects."
    ),
    responses={
        200: {
            "description": "SSE stream",
            "content": {"text/event-stream": {"example": "data: {}\\n\\n"}},
        }
    },
)
async def stream_telemetry(
    vehicle_id: UUID,
    user: Annotated[User, Depends(get_current_user_stream)],
    interval_seconds: Annotated[float | None, Query(gt=0, le=60)] = None,
) -> StreamingResponse:
    access_session = get_session_factory()()
    try:
        await ensure_vehicle_access(VehicleRepository(access_session), vehicle_id, user)
    finally:
        await access_session.close()
    interval = (
        interval_seconds
        if interval_seconds is not None
        else get_settings().telemetry_stream_poll_seconds
    )
    return StreamingResponse(
        _read_stream(
            vehicle_id,
            interval_seconds=interval,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
