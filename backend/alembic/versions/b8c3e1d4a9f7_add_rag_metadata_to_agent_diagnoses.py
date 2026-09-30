"""add rag metadata columns to agent_diagnoses

Revision ID: b8c3e1d4a9f7
Revises: 4f9d3c2b1a8e
Create Date: 2026-09-24 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8c3e1d4a9f7"
down_revision = "4f9d3c2b1a8e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_diagnoses",
        sa.Column(
            "rag_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "agent_diagnoses",
        sa.Column(
            "rag_evidence_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "agent_diagnoses",
        sa.Column("rag_embedding_model", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agent_diagnoses",
        sa.Column("rag_reranker_model", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agent_diagnoses",
        sa.Column("rag_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_diagnoses", "rag_scope")
    op.drop_column("agent_diagnoses", "rag_reranker_model")
    op.drop_column("agent_diagnoses", "rag_embedding_model")
    op.drop_column("agent_diagnoses", "rag_evidence_count")
    op.drop_column("agent_diagnoses", "rag_used")