from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_vehicle_health_service
from app.intelligence.models import HealthContext
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.vehicle_health import (
    HealthContextResponse,
    HealthSnapshotItem,
    LiveFreshnessState,
    LiveHealthStatusResponse,
)
from app.services.simulation_manager import get_simulation_manager
from app.services.vehicle_health_service import VehicleHealthService

router = APIRouter()


@router.post(
    "/analyze",
    response_model=HealthContextResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a historical health report",
    description=(
        "Run a deterministic health analysis over the vehicle's recent "
        "*historical* telemetry window and persist a labelled health snapshot "
        "(analysis_scope='historical_window'). The window is anchored at request "
        "time and may span several simulator runs and legacy (run-less) rows; it "
        "is never presented as current health. For the active current-session "
        "assessment use GET /health/live. Optionally override the analysis "
        "window size with window_minutes."
    ),
)
async def analyze_vehicle_health(
    vehicle_id: UUID,
    vehicle_health_service: Annotated[VehicleHealthService, Depends(get_vehicle_health_service)],
    user: Annotated[User, Depends(get_current_user)],
    window_minutes: Annotated[int | None, Query(ge=1, le=1440)] = None,
) -> HealthContextResponse:
    snapshot = await vehicle_health_service.analyze_vehicle_for_user(
        vehicle_id, user, window_minutes=window_minutes
    )
    return HealthContextResponse.model_validate(snapshot.context_json)


@router.get(
    "",
    response_model=HealthContextResponse,
    summary="Get latest historical health context",
    description=(
        "Returns the latest persisted Vehicle Health Context for the vehicle. "
        "This is a *historical* report (analysis_scope='historical_window' for "
        "window analyses, or the scope stored on older snapshots); it is not "
        "current health. Use GET /health/live for the active current session."
    ),
)
async def get_latest_health(
    vehicle_id: UUID,
    vehicle_health_service: Annotated[VehicleHealthService, Depends(get_vehicle_health_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> HealthContextResponse:
    snapshot = await vehicle_health_service.get_latest_for_user(vehicle_id, user)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No health snapshot exists for this vehicle; POST /analyze to generate one",
        )
    return HealthContextResponse.model_validate(snapshot.context_json)


@router.get(
    "/history",
    response_model=PaginatedResponse[HealthSnapshotItem],
    summary="List health history",
    description=(
        "Paginated list of a vehicle's health snapshots, newest first. "
        "Supports optional date filtering with start_time and end_time on generated_at."
    ),
)
async def list_health_history(
    vehicle_id: UUID,
    vehicle_health_service: Annotated[VehicleHealthService, Depends(get_vehicle_health_service)],
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    start_time: Annotated[
        datetime | None, Query(description="Inclusive lower bound (ISO 8601)")
    ] = None,
    end_time: Annotated[
        datetime | None, Query(description="Inclusive upper bound (ISO 8601)")
    ] = None,
) -> PaginatedResponse[HealthSnapshotItem]:
    snapshots, total = await vehicle_health_service.list_history_for_user(
        vehicle_id,
        user,
        page=page,
        page_size=page_size,
        start_time=start_time,
        end_time=end_time,
    )
    return PaginatedResponse(
        items=[HealthSnapshotItem.model_validate(s) for s in snapshots],
        page=page,
        page_size=page_size,
        total=total,
    )


def _derive_live_state(
    sufficiency_met: bool,
    sample_count: int,
    latest_sample_age_seconds: float | None,
    max_sample_age_seconds: float,
) -> LiveFreshnessState:
    """Map gate numbers to an honest freshness label."""
    if sample_count == 0:
        # A freshly spawned run starts in the collecting-data state with zero
        # samples; there is no evidence yet, but the session exists.
        return "collecting"
    if sufficiency_met:
        return "fresh"
    if (
        latest_sample_age_seconds is not None
        and latest_sample_age_seconds > max_sample_age_seconds
    ):
        return "stale"
    return "collecting"


@router.get(
    "/live",
    response_model=LiveHealthStatusResponse,
    summary="Get live current-session health",
    description=(
        "Evaluate the vehicle's *active simulator run* against the live "
        "sufficiency policy and return an honest current-session status: the "
        "simulator state, data freshness (fresh / collecting / stale), the "
        "current-run evidence counts, and -- only once enough fresh "
        "current-run evidence exists -- the definitive assessment. A stopped "
        "vehicle, a collecting session, or a stale feed never reuses an old "
        "snapshot as if it were current. This endpoint is read-only: it never "
        "persists a snapshot. For historical evidence use the "
        "health history or historical analytics endpoints."
    ),
)
async def live_vehicle_health(
    vehicle_id: UUID,
    vehicle_health_service: Annotated[VehicleHealthService, Depends(get_vehicle_health_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> LiveHealthStatusResponse:
    # Ownership is enforced below (raises 404 for unknown/unowned vehicles);
    # the latest snapshot also anchors ``last_evaluated_at`` when known.
    latest = await vehicle_health_service.get_latest_for_user(vehicle_id, user)

    simulation_manager = get_simulation_manager()
    sim_status = await simulation_manager.get_status(vehicle_id)
    run_id = await simulation_manager.active_run_id(vehicle_id)

    degraded_hint: str | None = None
    if sim_status.status == "degraded" and sim_status.error:
        degraded_hint = f"Simulator is degraded: {sim_status.error}"

    if run_id is None:
        return LiveHealthStatusResponse(
            vehicle_id=vehicle_id,
            run_id=None,
            simulator_state=sim_status.status,
            live_state="no_session",
            last_evaluated_at=latest.generated_at if latest else None,
            message=degraded_hint
            or "No simulator run is active for this vehicle; there is no current session to assess.",
        )

    snapshot = await vehicle_health_service.analyze_live_vehicle_for_user(
        vehicle_id, run_id, user, persist=False
    )
    context = HealthContext.model_validate(snapshot.context_json)
    data_quality = context.data_quality
    sufficiency = context.live_sufficiency

    latest_source_ts, latest_persisted_at = await vehicle_health_service.latest_run_evidence(
        vehicle_id, run_id
    )

    gate_met = sufficiency is not None and sufficiency.policy_met
    live_state = _derive_live_state(
        sufficiency_met=gate_met,
        sample_count=context.data_quality.sample_count,
        latest_sample_age_seconds=(
            sufficiency.latest_sample_age_seconds if sufficiency else None
        ),
        max_sample_age_seconds=(
            sufficiency.max_sample_age_seconds if sufficiency else 0.0
        ),
    )

    assessment = None
    message: str | None = degraded_hint
    if gate_met and sufficiency is not None:
        assessment = HealthContextResponse.from_context(context)
        message = message or "Live assessment is current and based on sufficient fresh session data."
    else:
        reasons = list(sufficiency.reasons) if sufficiency is not None else []
        if live_state == "stale":
            reasons.insert(
                0,
                "The current run's newest sample is older than the freshness "
                "limit; the feed appears stale.",
            )
        assessment = None
        if live_state == "stale":
            message = message or (
                "Current-session feed is stale; the live view is not being "
                "refreshed as expected."
            )
        elif sufficiency is not None and sufficiency.sample_count == 0:
            message = message or (
                "Run started but no current-run samples are persisted yet; "
                "assessment stays provisional while data collects."
            )
        elif sufficiency is not None:
            message = message or (
                "Not enough fresh current-session data yet; the assessment is "
                "provisional until the sufficiency gate clears."
            )
        elif message is None:
            message = (
                "Live evaluation produced no sufficiency details; treating as "
                "not enough evidence."
            )

    return LiveHealthStatusResponse(
        vehicle_id=vehicle_id,
        run_id=run_id,
        simulator_state=sim_status.status,
        live_state=live_state,
        latest_source_timestamp=latest_source_ts,
        latest_persisted_at=latest_persisted_at,
        sample_count=data_quality.sample_count,
        required_sample_count=sufficiency.required_sample_count if sufficiency else 0,
        observation_duration_seconds=(
            sufficiency.observation_duration_seconds if sufficiency else None
        ),
        required_duration_seconds=(
            sufficiency.required_duration_seconds if sufficiency else 0.0
        ),
        coverage_ratio=sufficiency.coverage_ratio if sufficiency else None,
        required_coverage=sufficiency.required_coverage if sufficiency else 0.0,
        latest_sample_age_seconds=(
            sufficiency.latest_sample_age_seconds if sufficiency else None
        ),
        max_sample_age_seconds=sufficiency.max_sample_age_seconds if sufficiency else 0.0,
        sample_timestamp_order_valid=data_quality.timestamp_order_valid,
        insufficiency_reasons=list(sufficiency.reasons) if sufficiency else [],
        assessment=assessment,
        last_evaluated_at=snapshot.generated_at,
        message=message,
    )
