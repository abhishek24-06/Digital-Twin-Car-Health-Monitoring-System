from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle

#: Alert lifecycle states. ``resolved`` is terminal: a condition that recurs
#: after resolution opens a *new* alert so the resolved record and its audit
#: trail are never rewritten.
ALERT_STATUS_OPEN = "open"
ALERT_STATUS_ACKNOWLEDGED = "acknowledged"
ALERT_STATUS_RESOLVED = "resolved"
ALERT_STATUSES: tuple[str, ...] = (
    ALERT_STATUS_OPEN,
    ALERT_STATUS_ACKNOWLEDGED,
    ALERT_STATUS_RESOLVED,
)
#: Alerts that still represent a live condition. Deduplication only folds a
#: repeated finding into an alert in one of these states; a resolved alert is
#: historical evidence and is never reopened in place.
ALERT_ACTIVE_STATUSES: tuple[str, ...] = (
    ALERT_STATUS_OPEN,
    ALERT_STATUS_ACKNOWLEDGED,
)

#: Severities an alert can carry. Only warning/critical findings become alerts.
ALERT_SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")

#: Alert lifecycle event types (the append-only audit history).
ALERT_EVENT_CREATED = "created"
ALERT_EVENT_RECURRED = "recurred"
ALERT_EVENT_ACKNOWLEDGED = "acknowledged"
ALERT_EVENT_RESOLVED = "resolved"


class Alert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A persistent, user-manageable alert derived from a live finding.

    Findings inside a health snapshot are immutable historical evidence. An
    alert is the mutable, first-class counterpart: it is created from a
    current-session finding, deduplicated by ``dedup_key`` while active,
    acknowledged and resolved by a user (or auto-resolved when the condition
    clears), and every transition is recorded in ``alert_events``.
    """

    __tablename__ = "alerts"

    vehicle_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: The simulation run that most recently produced the finding. Nullable so
    #: the shape stays valid for a legacy (run-less) window evaluation.
    simulation_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: Stable identity of the underlying condition (``{vehicle_id}:{rule_id}``).
    #: Deduplication folds repeats into the active alert with the same key.
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: True when the producing evaluation was provisional (insufficient fresh
    #: current-session evidence). Recorded so the UI never hides the caveat.
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: How many current-session evaluations have observed this condition while
    #: the alert stayed active.
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The raw finding dict (evidence) from the most recent observation.
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: The snapshot that most recently observed the condition (provenance).
    snapshot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledge_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    vehicle: Mapped[Vehicle] = relationship(
        back_populates="alerts",
        passive_deletes=True,
    )

    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AlertEvent.created_at",
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_alerts_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="ck_alerts_status",
        ),
        Index("ix_alerts_vehicle_status_last_seen", "vehicle_id", "status", "last_seen_at"),
        Index("ix_alerts_vehicle_dedup_key", "vehicle_id", "dedup_key"),
        Index("ix_alerts_vehicle_severity_last_seen", "vehicle_id", "severity", "last_seen_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Alert id={self.id} vehicle_id={self.vehicle_id} "
            f"rule={self.rule_id!r} severity={self.severity!r} status={self.status!r}>"
        )


class AlertEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only audit entry for one alert lifecycle transition.

    ``actor_user_id`` is null for automated transitions (creation, recurrence,
    automatic resolution) and set for user actions (acknowledge, resolve).
    """

    __tablename__ = "alert_events"

    alert_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    alert: Mapped[Alert] = relationship(back_populates="events")

    __table_args__ = (Index("ix_alert_events_alert_created", "alert_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<AlertEvent id={self.id} alert_id={self.alert_id} type={self.event_type!r}>"
