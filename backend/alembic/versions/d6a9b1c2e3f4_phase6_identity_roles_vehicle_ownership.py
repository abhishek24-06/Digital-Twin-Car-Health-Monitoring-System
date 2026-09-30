"""phase 6 identity, roles, and vehicle ownership

Revision ID: d6a9b1c2e3f4
Revises: b8c3e1d4a9f7
Create Date: 2026-09-25 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d6a9b1c2e3f4"
down_revision = "b8c3e1d4a9f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users table (accounts, roles) ---
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # --- refresh_tokens (rotating, hash-only storage) ---
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    # --- vehicles: ownership + lifecycle columns ---
    op.add_column("vehicles", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_vehicles_owner_user_id_users",
        "vehicles",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_vehicles_owner_user_id", "vehicles", ["owner_user_id"])
    op.add_column(
        "vehicles",
        sa.Column("source_type", sa.String(length=16), nullable=False, server_default="simulator"),
    )
    op.add_column(
        "vehicles",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
    )
    op.add_column(
        "vehicles",
        sa.Column(
            "simulation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_check_constraint("ck_vehicles_source_type", "vehicles", "source_type IN ('simulator', 'real')")
    op.create_check_constraint("ck_vehicles_status", "vehicles", "status IN ('active', 'disabled')")

    # --- agent_diagnoses: attribution ---
    op.add_column(
        "agent_diagnoses",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_diagnoses_user_id_users",
        "agent_diagnoses",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_diagnoses_user_id_users", "agent_diagnoses", type_="foreignkey")
    op.drop_column("agent_diagnoses", "user_id")

    op.drop_constraint("ck_vehicles_status", "vehicles", type_="check")
    op.drop_constraint("ck_vehicles_source_type", "vehicles", type_="check")
    op.drop_column("vehicles", "simulation_enabled")
    op.drop_column("vehicles", "status")
    op.drop_column("vehicles", "source_type")
    op.drop_index("ix_vehicles_owner_user_id", table_name="vehicles")
    op.drop_constraint("fk_vehicles_owner_user_id_users", "vehicles", type_="foreignkey")
    op.drop_column("vehicles", "owner_user_id")

    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")