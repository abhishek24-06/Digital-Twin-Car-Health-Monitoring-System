from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle


class TelemetryRecord(UUIDPrimaryKeyMixin, Base):
    """A single raw telemetry sample captured from a vehicle."""

    __tablename__ = "telemetry_records"

    vehicle_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )

    rpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    coolant_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    oil_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    fuel_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    intake_air_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    throttle_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine_runtime: Mapped[float | None] = mapped_column(Float, nullable=True)
    odometer: Mapped[float | None] = mapped_column(Float, nullable=True)

    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    vehicle: Mapped[Vehicle] = relationship(
        back_populates="telemetry_records",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_telemetry_records_vehicle_id_timestamp", "vehicle_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<TelemetryRecord id={self.id} vehicle_id={self.vehicle_id}>"
