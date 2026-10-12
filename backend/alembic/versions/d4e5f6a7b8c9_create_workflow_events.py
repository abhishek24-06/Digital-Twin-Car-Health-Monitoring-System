"""create workflow_events durable observability history

Revision ID: d4e5f6a7b8c9
Revises: c3f7a2d5e9b1
Create Date: 2026-10-11

Adds the ``workflow_events`` table: a bounded, restart-surviving audit copy of
the workflow observability events. The process-local event bus stays the
real-time feed; this table is history for post-incident review. ``event_id`` is
unique so re-persisting an event is idempotent. No foreign keys are declared:
observability history must outlive vehicle/document lifecycle changes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4e5f6a7b8c9"
down_revision = "c3f7a2d5e9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workflow", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_workflow_events_event_id"),
    )
    op.create_index("ix_workflow_events_timestamp", "workflow_events", ["timestamp"])
    op.create_index(
        "ix_workflow_events_vehicle_timestamp",
        "workflow_events",
        ["vehicle_id", "timestamp"],
    )
    op.create_index(
        "ix_workflow_events_workflow_timestamp",
        "workflow_events",
        ["workflow", "timestamp"],
    )
    op.create_index(
        "ix_workflow_events_correlation_id", "workflow_events", ["correlation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_events_correlation_id", table_name="workflow_events")
    op.drop_index("ix_workflow_events_workflow_timestamp", table_name="workflow_events")
    op.drop_index("ix_workflow_events_vehicle_timestamp", table_name="workflow_events")
    op.drop_index("ix_workflow_events_timestamp", table_name="workflow_events")
    op.drop_table("workflow_events")
