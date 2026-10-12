from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_alert_service
from app.models.user import User
from app.schemas.alert import (
    AlertActionRequest,
    AlertDetail,
    AlertEventItem,
    AlertItem,
)
from app.schemas.common import PaginatedResponse
from app.services.alert_service import AlertService

router = APIRouter()

AlertStatusFilter = Literal["open", "acknowledged", "resolved"]
AlertSeverityFilter = Literal["info", "warning", "critical"]


def _to_detail(alert, events) -> AlertDetail:
    """Compose a detail response without touching the lazy ``events`` relation."""
    item = AlertItem.model_validate(alert)
    return AlertDetail(
        **item.model_dump(),
        evidence=alert.evidence,
        events=[AlertEventItem.model_validate(event) for event in events],
    )


@router.get(
    "",
    response_model=PaginatedResponse[AlertItem],
    summary="List a vehicle's persistent alerts",
    description=(
        "Paginated, most-severe-first list of the vehicle's alerts. Persisted "
        "alerts are created from current-session warning/critical findings by "
        "the background monitor; historical (windowed) analyses never create "
        "alerts. Optional `status` (repeatable) and `severity` filters narrow "
        "the result."
    ),
)
async def list_alerts(
    vehicle_id: UUID,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
    user: Annotated[User, Depends(get_current_user)],
    status_filter: Annotated[
        list[AlertStatusFilter] | None,
        Query(alias="status", description="Repeat to filter by several statuses"),
    ] = None,
    severity: Annotated[AlertSeverityFilter | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[AlertItem]:
    alerts, total = await alert_service.list_for_user(
        vehicle_id,
        user,
        statuses=list(status_filter) if status_filter else None,
        severity=severity,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        items=[AlertItem.model_validate(alert) for alert in alerts],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/{alert_id}",
    response_model=AlertDetail,
    summary="Get one alert with its full audit history",
)
async def get_alert(
    vehicle_id: UUID,
    alert_id: UUID,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> AlertDetail:
    alert, events = await alert_service.get_for_user(vehicle_id, alert_id, user)
    return _to_detail(alert, events)


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertDetail,
    summary="Acknowledge an alert",
    description=(
        "Move an open alert to `acknowledged` and record the transition (and "
        "optional note) in the audit history. A resolved alert cannot be "
        "acknowledged; re-acknowledging an acknowledged alert is a no-op."
    ),
)
async def acknowledge_alert(
    vehicle_id: UUID,
    alert_id: UUID,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
    user: Annotated[User, Depends(get_current_user)],
    payload: Annotated[AlertActionRequest | None, Body()] = None,
) -> AlertDetail:
    await alert_service.acknowledge_for_user(
        vehicle_id, alert_id, user, note=payload.note if payload else None
    )
    alert, events = await alert_service.get_for_user(vehicle_id, alert_id, user)
    return _to_detail(alert, events)


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertDetail,
    summary="Resolve an alert",
    description=(
        "Move an open or acknowledged alert to `resolved` and record the "
        "transition (and optional note) in the audit history. Resolving an "
        "already-resolved alert is a no-op. A resolved alert is terminal: a "
        "recurrence creates a new alert rather than reopening the old one."
    ),
)
async def resolve_alert(
    vehicle_id: UUID,
    alert_id: UUID,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
    user: Annotated[User, Depends(get_current_user)],
    payload: Annotated[AlertActionRequest | None, Body()] = None,
) -> AlertDetail:
    await alert_service.resolve_for_user(
        vehicle_id, alert_id, user, note=payload.note if payload else None
    )
    alert, events = await alert_service.get_for_user(vehicle_id, alert_id, user)
    return _to_detail(alert, events)
