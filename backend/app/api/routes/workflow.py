"""Workflow observability API routes.

Provides real-time event streaming (SSE) and recent event queries
for the Workflow Monitor frontend.
"""

from __future__ import annotations

import asyncio
import logging
import typing
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.dependencies.auth import get_current_user, get_current_user_stream
from app.dependencies.database import get_db
from app.models.user import User
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.workflow import (
    WorkflowEvent,
    WorkflowEventFilters,
    WorkflowEventResponse,
    WorkflowRecentResponse,
    WorkflowStage,
    WorkflowStateResponse,
    WorkflowStatus,
    WorkflowStatusResponse,
    WorkflowType,
)
from app.services.simulation_manager import get_simulation_manager
from app.services.subscriber_manager import get_subscriber_supervisor
from app.services.telemetry_pipeline_state import (
    HealthEvaluationFailure,
    build_vehicle_state,
)
from app.services.vehicle_service import VehicleService
from app.services.workflow_event_bus import (
    get_workflow_event_bus,
    publish_workflow_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow", tags=["Workflow"])


async def _owned_vehicle_ids(session: AsyncSession, user: User) -> set[UUID] | None:
    """Vehicle ids the caller may see, or ``None`` for an unrestricted admin.

    Computed once per request/connection so visibility filtering never costs a
    query per event.
    """
    if user.is_admin:
        return None
    return set(await VehicleRepository(session).list_ids_by_owner(user.id))


async def _resolve_visible_vehicle_ids(user: User) -> set[UUID] | None:
    """Same as :func:`_owned_vehicle_ids` but with a short-lived session.

    The SSE stream can live for minutes; it must not pin a pooled database
    connection for the whole duration, so the owned-id set is resolved once
    through a session that is opened and released immediately.
    """
    if user.is_admin:
        return None
    async with get_session_factory()() as session:
        return set(await VehicleRepository(session).list_ids_by_owner(user.id))


def _is_event_visible(event: WorkflowEvent, owned_vehicle_ids: set[UUID] | None) -> bool:
    """Server-side workflow-event visibility.

    ``None`` means an admin (unrestricted). Otherwise the caller sees only
    events for vehicles they own, plus non-vehicle (global) events -- except
    ``rag_ingestion``, which is admin-only and must never let a non-admin infer
    a private ingestion operation.
    """
    if owned_vehicle_ids is None:
        return True
    if event.workflow == WorkflowType.RAG_INGESTION:
        return False
    if event.vehicle_id is None:
        return True
    return event.vehicle_id in owned_vehicle_ids


def _event_to_response(event) -> WorkflowEventResponse:
    """Convert internal WorkflowEvent to API response."""
    return WorkflowEventResponse(
        event_id=event.event_id,
        timestamp=event.timestamp,
        workflow=event.workflow,
        stage=event.stage,
        status=event.status,
        message=event.message,
        vehicle_id=event.vehicle_id,
        document_id=event.document_id,
        correlation_id=event.correlation_id,
        duration_ms=event.duration_ms,
        metadata=event.metadata,
    )


async def _latest_health_failures() -> dict[UUID, HealthEvaluationFailure]:
    """Most recent failed health evaluation per vehicle, from the event bus.

    The health monitor publishes one ``error`` event per vehicle whose analysis
    failed this pass. Derived state consults these so a monitor that is enabled
    but failing reports ``degraded`` with a reason instead of a hollow
    "awaiting a snapshot". Newest-first iteration lets the first hit per vehicle
    win; a later successful snapshot supersedes it in the derivation.
    """
    bus = get_workflow_event_bus()
    failures: dict[UUID, HealthEvaluationFailure] = {}
    for event in await bus.get_recent(limit=bus.capacity):
        if (
            event.workflow == WorkflowType.HEALTH
            and event.stage == WorkflowStage.HEALTH_ANALYSIS_STARTED
            and event.status == WorkflowStatus.ERROR
            and event.vehicle_id is not None
            and event.vehicle_id not in failures
        ):
            failures[event.vehicle_id] = HealthEvaluationFailure(
                at=event.timestamp,
                message=event.message,
            )
    return failures


@router.get(
    "/events/recent",
    response_model=WorkflowRecentResponse,
    summary="Get recent workflow events",
    description=(
        "Return paginated recent workflow events, newest first. "
        "Supports filtering by workflow, stage, status, vehicle, document, "
        "and time range. Maximum limit is 500 events."
    ),
)
async def get_recent_events(
    filters: Annotated[WorkflowEventFilters, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> WorkflowRecentResponse:
    """Get recent workflow events with optional filtering."""
    bus = get_workflow_event_bus()
    owned_vehicle_ids = await _owned_vehicle_ids(session, user)

    # Get all events (newest first) then apply filters
    all_events = await bus.get_recent(limit=filters.limit + filters.offset, offset=0)

    # Apply filters
    filtered = []
    for event in all_events:
        if not _is_event_visible(event, owned_vehicle_ids):
            continue
        if filters.workflow and event.workflow != filters.workflow:
            continue
        if filters.stage and event.stage != filters.stage:
            continue
        if filters.status and event.status != filters.status:
            continue
        if filters.vehicle_id and event.vehicle_id != filters.vehicle_id:
            continue
        if filters.document_id and event.document_id != filters.document_id:
            continue
        if filters.correlation_id and event.correlation_id != filters.correlation_id:
            continue
        if filters.since and event.timestamp < filters.since:
            continue
        if filters.until and event.timestamp > filters.until:
            continue
        filtered.append(event)

    total = len(filtered)
    paginated = filtered[filters.offset : filters.offset + filters.limit]

    return WorkflowRecentResponse(
        items=[_event_to_response(e) for e in paginated],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.get(
    "/events/stream",
    summary="Stream live workflow events",
    description=(
        "Server-sent events stream of live workflow events. "
        "Each event is a JSON document. Heartbeat comments are emitted "
        "every N seconds (configurable) to keep the connection alive. "
        "The stream closes when the client disconnects."
    ),
    responses={
        200: {
            "description": "SSE stream",
            "content": {"text/event-stream": {"example": "data: {}\n\n"}},
        }
    },
)
async def stream_events(
    request: Request,
    user: Annotated[User, Depends(get_current_user_stream)],
    workflow: Annotated[str | None, Query(description="Filter by workflow type")] = None,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    vehicle_id: Annotated[str | None, Query(description="Filter by vehicle ID")] = None,
    document_id: Annotated[str | None, Query(description="Filter by document ID")] = None,
    correlation_id: Annotated[str | None, Query(description="Filter by correlation ID")] = None,
) -> StreamingResponse:
    """Stream live workflow events via Server-Sent Events."""
    bus = get_workflow_event_bus()
    settings = get_settings()
    heartbeat_interval = settings.workflow_sse_heartbeat_seconds

    async def event_generator() -> typing.AsyncGenerator[str, None]:
        owned_vehicle_ids = await _resolve_visible_vehicle_ids(user)
        sub_id, queue = await bus.subscribe()
        last_heartbeat = asyncio.get_event_loop().time()
        try:
            # Send initial connection event
            conn_event = WorkflowEvent(
                workflow=WorkflowType.SYSTEM,
                stage=WorkflowStage.STREAM_CONNECTED,
                status=WorkflowStatus.SUCCESS,
                message="Workflow monitor connected",
                metadata={"connection": "established"},
            )
            yield f"data: {_event_to_response(conn_event).model_dump_json()}\n\n"

            while True:
                try:
                    # Wait for event with timeout for heartbeat
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    if event is None:  # Shutdown sentinel
                        break

                    # Server-side visibility: never leak another user's
                    # vehicle events and never expose rag_ingestion to
                    # non-admins.
                    if not _is_event_visible(event, owned_vehicle_ids):
                        continue

                    # Apply filters
                    if workflow and event.workflow != workflow:
                        continue
                    if status and event.status != status:
                        continue
                    if vehicle_id and event.vehicle_id != vehicle_id:
                        continue
                    if document_id and event.document_id != document_id:
                        continue
                    if correlation_id and event.correlation_id != correlation_id:
                        continue

                    yield f"data: {_event_to_response(event).model_dump_json()}\n\n"

                except TimeoutError:
                    # Check if client disconnected
                    if await request.is_disconnected():
                        break
                    # Heartbeat
                    now = asyncio.get_event_loop().time()
                    if now - last_heartbeat >= heartbeat_interval:
                        yield ": ping\n\n"
                        last_heartbeat = now
                    continue

        except asyncio.CancelledError:
            # Client disconnected
            pass
        finally:
            await bus.unsubscribe(sub_id)
            await publish_workflow_event(
                workflow=WorkflowType.SYSTEM,
                stage=WorkflowStage.STREAM_DISCONNECTED,
                status=WorkflowStatus.SUCCESS,
                message="Workflow monitor disconnected",
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/status",
    response_model=WorkflowStatusResponse,
    summary="Get workflow system status",
    description="Return high-level status of all workflow pipelines.",
)
async def get_workflow_status(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowStatusResponse:
    """Get high-level workflow system status."""
    bus = get_workflow_event_bus()
    bus_status = await bus.get_status()

    # Check subscriber
    sub_supervisor = get_subscriber_supervisor()
    sub_health = await sub_supervisor.health()

    # Check for recent telemetry activity (last 30 seconds)
    cutoff = datetime.now(UTC) - timedelta(seconds=30)
    repo = TelemetryRepository(session)
    recent_count = await repo.count_since(cutoff)

    # Active simulations
    sim_manager = get_simulation_manager()
    active_sims = 0
    async with sim_manager._lock:
        for inst in sim_manager._instances.values():
            if inst.status in ("starting", "running", "stopping"):
                active_sims += 1

    return WorkflowStatusResponse(
        telemetry_pipeline_active=sub_health.running and recent_count > 0,
        rag_pipeline_active=True,
        agent_pipeline_active=True,
        subscriber_running=sub_health.running,
        active_simulations=active_sims,
        events_in_buffer=bus_status["events_in_buffer"],
        oldest_event_ts=bus_status["oldest_event_ts"],
        newest_event_ts=bus_status["newest_event_ts"],
    )


@router.get(
    "/state",
    response_model=WorkflowStateResponse,
    summary="Get derived telemetry pipeline state",
    description=(
        "Read-only, derived snapshot of how far each accessible vehicle's "
        "telemetry has actually flowed (simulator, MQTT publish/broker/"
        "subscriber, parser, Postgres, health engine/snapshot). Stages are "
        "derived from real process and database signals -- never fabricated, "
        "and never reported as directly observed events."
    ),
)
async def get_workflow_state(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    vehicle_id: Annotated[UUID | None, Query(description="Filter to a single vehicle")] = None,
) -> WorkflowStateResponse:
    """Derived telemetry pipeline state for one or all accessible vehicles."""
    manager = get_simulation_manager()
    subscriber = get_subscriber_supervisor()
    failures = await _latest_health_failures()

    if vehicle_id is not None:
        owned_vehicle_ids = await _owned_vehicle_ids(session, user)
        # Non-admins asking for someone else's vehicle get an honest, empty
        # result rather than a leaky 404.
        if owned_vehicle_ids is not None and vehicle_id not in owned_vehicle_ids:
            return WorkflowStateResponse(items=[])
        vehicle_ids: list[UUID] = [vehicle_id]
    else:
        vehicles, _ = await VehicleService(
            session, VehicleRepository(session)
        ).list_vehicles_for_user(user, page=1, page_size=500)
        vehicle_ids = [vehicle.id for vehicle in vehicles]

    items = [
        await build_vehicle_state(
            session,
            manager,
            subscriber,
            vehicle_id=vid,
            last_health_failure=failures.get(vid),
        )
        for vid in vehicle_ids
    ]
    return WorkflowStateResponse(items=items)
