"""create agent_diagnoses

Revision ID: c7f2e8a1b3d4
Revises: a1b2c3d4e5f6
Create Date: 2026-09-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c7f2e8a1b3d4"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_diagnoses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", sa.String(length=64), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("user_query", sa.Text(), nullable=True),
        sa.Column("diagnosis", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="completed", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("context_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_diagnoses_vehicle_created_at",
        "agent_diagnoses",
        ["vehicle_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_diagnoses_vehicle_trigger_created",
        "agent_diagnoses",
        ["vehicle_id", "trigger_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_diagnoses_vehicle_trigger_created", table_name="agent_diagnoses")
    op.drop_index("ix_agent_diagnoses_vehicle_created_at", table_name="agent_diagnoses")
    op.drop_table("agent_diagnoses")