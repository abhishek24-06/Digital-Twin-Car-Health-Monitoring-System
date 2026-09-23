"""Request and response schemas for the Phase 4 agent API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agent.schemas import DiagnosisResponse
from app.schemas.common import PaginatedResponse
from app.schemas.vehicle_health import HealthContextResponse

__all__ = [
    "AgentDiagnosisItem",
    "AgentQueryRequest",
    "CriticalEventRequest",
    "DashboardResponse",
    "PaginatedResponse",
]


class AgentQueryRequest(BaseModel):
    """A natural-language question about a vehicle."""

    query: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(str_strip_whitespace=True)


class CriticalEventRequest(BaseModel):
    """A critical telemetry rule event to diagnose (rule ids optional)."""

    rule_ids: list[str] | None = Field(
        default=None,
        max_length=100,
        description="Rule ids that triggered the critical event; derived from the "
        "context when omitted.",
    )


class AgentDiagnosisItem(BaseModel):
    """Lightweight history entry exposing the queryable diagnosis columns."""

    id: UUID
    vehicle_id: UUID
    trigger_type: str
    severity: str
    confidence: float | None = None
    status: str
    error_code: str | None = None
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False
    latency_ms: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DashboardResponse(BaseModel):
    """Dashboard hook: current health context plus latest diagnosis (no LLM)."""

    vehicle_id: UUID
    generated_at: datetime
    health_context: HealthContextResponse | None = None
    latest_diagnosis: DiagnosisResponse | None = None
    diagnosis_age_seconds: float | None = None
