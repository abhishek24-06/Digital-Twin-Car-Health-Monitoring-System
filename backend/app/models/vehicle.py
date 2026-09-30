from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent_diagnosis import AgentDiagnosis
    from app.models.health_snapshot import HealthSnapshot
    from app.models.telemetry import TelemetryRecord
    from app.models.user import User

SOURCE_TYPE_SIMULATOR = "simulator"
SOURCE_TYPE_REAL = "real"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


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

    owner_user_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(16), default=SOURCE_TYPE_SIMULATOR, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE, nullable=False)
    simulation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    owner: Mapped[User | None] = relationship(back_populates="vehicles")

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

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('simulator', 'real')",
            name="ck_vehicles_source_type",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_vehicles_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<Vehicle id={self.id} vin={self.vin!r} make={self.make!r}>"
