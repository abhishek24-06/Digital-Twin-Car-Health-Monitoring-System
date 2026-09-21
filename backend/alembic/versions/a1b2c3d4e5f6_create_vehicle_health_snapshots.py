"""create vehicle_health_snapshots

Revision ID: a1b2c3d4e5f6
Revises: 7e38f4f3d70b
Create Date: 2026-09-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '7e38f4f3d70b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vehicle_health_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vehicle_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False),
        sa.Column('health_score', sa.Float(), nullable=True),
        sa.Column('health_status', sa.String(length=20), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('context_schema_version', sa.String(length=16), nullable=False),
        sa.Column('context_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_vehicle_health_snapshots_vehicle_generated_at',
        'vehicle_health_snapshots',
        ['vehicle_id', 'generated_at'],
        unique=False,
    )
    op.create_index(
        'ix_vehicle_health_snapshots_vehicle_status_generated',
        'vehicle_health_snapshots',
        ['vehicle_id', 'health_status', 'generated_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_vehicle_health_snapshots_vehicle_status_generated', table_name='vehicle_health_snapshots')
    op.drop_index('ix_vehicle_health_snapshots_vehicle_generated_at', table_name='vehicle_health_snapshots')
    op.drop_table('vehicle_health_snapshots')