from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.vehicle import Vehicle


class AgentDiagnosis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A persisted agent diagnosis for a vehicle.

    The full structured response lives in the ``diagnosis`` JSONB column while
    the most commonly queried fields are promoted to first-class columns so
    history/dedup lookups stay indexed and cheap.
    """

    __tablename__ = "agent_diagnoses"

    vehicle_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    user_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rag_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rag_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rag_embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rag_reranker_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rag_scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    vehicle: Mapped[Vehicle] = relationship(
        back_populates="agent_diagnoses",
        passive_deletes=True,
    )

    user: Mapped[User | None] = relationship()

    __table_args__ = (
        Index(
            "ix_agent_diagnoses_vehicle_created_at",
            "vehicle_id",
            "created_at",
        ),
        Index(
            "ix_agent_diagnoses_vehicle_trigger_created",
            "vehicle_id",
            "trigger_type",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentDiagnosis id={self.id} vehicle_id={self.vehicle_id} "
            f"trigger={self.trigger_type!r} status={self.status!r}>"
        )
