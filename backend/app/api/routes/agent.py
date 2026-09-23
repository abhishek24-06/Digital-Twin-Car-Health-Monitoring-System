"""Phase 4 agent API endpoints.

All endpoints live under ``/vehicles/{vehicle_id}/agent`` and route through
:class:`app.agent.service.AgentService`. Only user queries and critical events
invoke the LLM; the dashboard hook and history endpoints never do.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.agent.schemas import DiagnosisResponse
from app.agent.service import AgentService
from app.dependencies.database import get_agent_service
from app.schemas.agent import (
    AgentDiagnosisItem,
    AgentQueryRequest,
    CriticalEventRequest,
    DashboardResponse,
    PaginatedResponse,
)
from app.schemas.vehicle_health import HealthContextResponse

router = APIRouter()


@router.post(
    "/query",
    response_model=DiagnosisResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a natural-language question about a vehicle",
    description=(
        "Interprets the vehicle's latest Health Context through the reasoning "
        "agent and returns a grounded, persisted structured diagnosis."
    ),
)
async def ask_agent(
    vehicle_id: UUID,
    payload: AgentQueryRequest,
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
) -> DiagnosisResponse:
    return await agent_service.run_user_query(vehicle_id, payload.query)


@router.post(
    "/events/critical",
    response_model=DiagnosisResponse,
    status_code=status.HTTP_200_OK,
    summary="Diagnose a critical telemetry rule event",
    description=(
        "Runs a critical-event diagnosis. Repeated events for the same vehicle "
        "and rule set within the cooldown window return the existing diagnosis "
        "instead of calling the LLM again."
    ),
)
async def diagnose_critical_event(
    vehicle_id: UUID,
    payload: CriticalEventRequest,
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
) -> DiagnosisResponse:
    return await agent_service.run_critical_event(vehicle_id, payload.rule_ids)


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Dashboard hook (no LLM call)",
    description=(
        "Reads-only snapshot for dashboards: the latest health context, the "
        "latest agent diagnosis and its age. Never invokes the LLM."
    ),
)
async def agent_dashboard(
    vehicle_id: UUID,
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
) -> DashboardResponse:
    payload = await agent_service.get_dashboard_context(vehicle_id)
    return DashboardResponse(
        vehicle_id=payload["vehicle_id"],
        generated_at=payload["generated_at"],
        health_context=(
            HealthContextResponse.model_validate(payload["health_context"])
            if payload["health_context"] is not None
            else None
        ),
        latest_diagnosis=(
            DiagnosisResponse.model_validate(payload["latest_diagnosis"])
            if payload["latest_diagnosis"] is not None
            else None
        ),
        diagnosis_age_seconds=payload["diagnosis_age_seconds"],
    )


@router.get(
    "/diagnoses",
    response_model=PaginatedResponse[AgentDiagnosisItem],
    summary="List agent diagnosis history",
    description="Paginated list of a vehicle's agent diagnoses, newest first.",
)
async def list_agent_diagnoses(
    vehicle_id: UUID,
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[AgentDiagnosisItem]:
    records, total = await agent_service.list_diagnoses(vehicle_id, page=page, page_size=page_size)
    return PaginatedResponse(
        items=[AgentDiagnosisItem.model_validate(record) for record in records],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/diagnoses/latest",
    response_model=DiagnosisResponse,
    summary="Get the latest agent diagnosis",
    description="Returns the most recent agent diagnosis for the vehicle.",
)
async def get_latest_agent_diagnosis(
    vehicle_id: UUID,
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
) -> DiagnosisResponse:
    record = await agent_service.get_latest_diagnosis(vehicle_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="No agent diagnosis exists for this vehicle",
        )
    return DiagnosisResponse.model_validate(record.diagnosis)
