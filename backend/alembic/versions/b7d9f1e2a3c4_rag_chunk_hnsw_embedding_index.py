"""schema parity: rag_chunk embedding HNSW index.

Revision ID: b7d9f1e2a3c4
Revises: d6a9b1c2e3f4
Create Date: 2026-10-07 00:00:00.000000

Why this exists
---------------
The Supabase schema was previously rebuilt outside Alembic (a DROP SCHEMA
CASCADE + re-create). The ORM tables, columns and most indexes now match the
migration head exactly, but ``ix_rag_chunk_embedding`` is created *only* in
migration ``4f9d3c2b1a8e`` (it is not part of the ORM metadata used by
``create_all``), so it did not survive and vector similarity search would fall
back to a sequential scan. This migration adds exactly that one index and is
idempotent (``IF NOT EXISTS``), so it is safe on any database, at any revision.
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d9f1e2a3c4"
down_revision = "d6a9b1c2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    am_rows = connection.execute(sa.text("SELECT 1 FROM pg_am WHERE amname = 'hnsw'")).all()
    if not am_rows:
        raise RuntimeError(
            "pgvector's HNSW access method is not available in this PostgreSQL server. "
            "Install/enable pgvector before applying this migration."
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunk_embedding ON rag_chunks "
        "USING hnsw (embedding_store vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rag_chunk_embedding")