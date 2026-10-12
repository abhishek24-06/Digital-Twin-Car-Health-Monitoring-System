"""add simulation_run_id to telemetry_records

Revision ID: c3f7a2d5e9b1
Revises: b7d9f1e2a3c4
Create Date: 2026-10-11 09:00:00.000000

Adds nullable ``simulation_run_id`` (simulator-run provenance) to
``telemetry_records``. Existing rows keep ``NULL`` -- legacy telemetry is never
assigned fabricated provenance. The new ``(vehicle_id, simulation_run_id,
timestamp)`` index serves the current-session live analysis query; the
event-id unique constraint is untouched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3f7a2d5e9b1"
down_revision: Union[str, None] = "b7d9f1e2a3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telemetry_records",
        sa.Column("simulation_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_telemetry_records_vehicle_run_timestamp",
        "telemetry_records",
        ["vehicle_id", "simulation_run_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_records_vehicle_run_timestamp", table_name="telemetry_records")
    op.drop_column("telemetry_records", "simulation_run_id")