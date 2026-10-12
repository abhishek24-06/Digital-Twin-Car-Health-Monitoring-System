"""API schemas for persistent vehicle alerts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AlertEventItem(BaseModel):
    """One entry in an alert's append-only audit history."""

    id: UUID
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    actor_user_id: UUID | None = None
    note: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertItem(BaseModel):
    """A persisted alert (list view: queryable columns, no raw evidence)."""

    id: UUID
    vehicle_id: UUID
    simulation_run_id: UUID | None = None
    rule_id: str
    category: str | None = None
    severity: str
    status: str
    title: str
    message: str
    metric: str | None = None
    observed_value: float | None = None
    threshold: float | None = None
    unit: str | None = None
    confidence: float | None = None
    provisional: bool
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    snapshot_id: UUID | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: UUID | None = None
    acknowledge_note: str | None = None
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertDetail(AlertItem):
    """An alert plus its raw finding evidence and full audit history."""

    evidence: dict[str, Any] | None = None
    events: list[AlertEventItem] = Field(default_factory=list)


class AlertActionRequest(BaseModel):
    """Optional operator note attached to an acknowledge/resolve action."""

    note: str | None = Field(default=None, max_length=2000)
