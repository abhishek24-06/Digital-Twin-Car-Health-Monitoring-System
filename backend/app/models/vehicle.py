from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent_diagnosis import AgentDiagnosis
    from app.models.health_snapshot import HealthSnapshot
    from app.models.telemetry import TelemetryRecord


class Vehicle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered vehicle (the top-level entity of the platform)."""

    __tablename__ = "vehicles"

    vin: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    engine_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    telemetry_records: Mapped[list[TelemetryRecord]] = relationship(
        back_populates="vehicle",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    health_snapshots: Mapped[list[HealthSnapshot]] = relationship(
        back_populates="vehicle",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    agent_diagnoses: Mapped[list[AgentDiagnosis]] = relationship(
        back_populates="vehicle",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Vehicle id={self.id} vin={self.vin!r} make={self.make!r}>"
