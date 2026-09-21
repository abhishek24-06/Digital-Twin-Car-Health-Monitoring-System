from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle


class HealthSnapshot(UUIDPrimaryKeyMixin, Base):
    """An immutable, persisted Vehicle Health Context.

    A snapshot is historical evidence: re-analysis creates a new snapshot and
    never mutates an existing one.
    """

    __tablename__ = "vehicle_health_snapshots"

    vehicle_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    health_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    vehicle: Mapped[Vehicle] = relationship(
        back_populates="health_snapshots",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "ix_vehicle_health_snapshots_vehicle_generated_at",
            "vehicle_id",
            "generated_at",
        ),
        Index(
            "ix_vehicle_health_snapshots_vehicle_status_generated",
            "vehicle_id",
            "health_status",
            "generated_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<HealthSnapshot id={self.id} vehicle_id={self.vehicle_id} "
            f"status={self.health_status!r} score={self.health_score}>"
        )
