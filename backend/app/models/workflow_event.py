from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Float, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class WorkflowEventRecord(UUIDPrimaryKeyMixin, Base):
    """Durable, bounded audit copy of one workflow observability event.

    The process-local ring buffer (``WorkflowEventBus``) remains the real-time
    feed for SSE; this table is restart-surviving history for post-incident
    review. It is deliberately *not* the live source: core business code never
    reads it, so a persistence failure degrades observability history only.

    ``event_id`` is unique so re-persisting the same event is idempotent, and no
    foreign keys are declared: observability history must outlive (and never
    block) vehicle/document lifecycle changes.
    """

    __tablename__ = "workflow_events"

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    workflow: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The Python attribute cannot be named ``metadata`` (reserved on the
    # declarative base); the database column keeps the event-model name.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_workflow_events_timestamp", "timestamp"),
        Index("ix_workflow_events_vehicle_timestamp", "vehicle_id", "timestamp"),
        Index("ix_workflow_events_workflow_timestamp", "workflow", "timestamp"),
        Index("ix_workflow_events_correlation_id", "correlation_id"),
    )
