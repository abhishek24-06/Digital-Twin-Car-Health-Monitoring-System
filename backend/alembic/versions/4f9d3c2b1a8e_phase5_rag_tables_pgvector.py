"""phase5 rag tables: documents, versions, chunks + pgvector

Revision ID: 4f9d3c2b1a8e
Revises: c7f2e8a1b3d4
Create Date: 2026-09-24 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "4f9d3c2b1a8e"
down_revision = "c7f2e8a1b3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("canonical_source", sa.String(512), nullable=True, unique=True),
        sa.Column("source_uri", sa.String(1024), nullable=True),
        sa.Column("manufacturer", sa.String(128), nullable=True),
        sa.Column("make", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("model_year_start", sa.Integer(), nullable=True),
        sa.Column("model_year_end", sa.Integer(), nullable=True),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_documents_manufacturer",
        "rag_documents",
        ["manufacturer"],
        unique=False,
    )
    op.create_index(
        "ix_rag_documents_make_model",
        "rag_documents",
        ["make", "model"],
        unique=False,
    )

    op.create_table(
        "rag_document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column("parser_name", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("chunking_version", sa.String(32), nullable=False),
        sa.Column("ingestion_status", sa.String(16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["rag_documents.id"], name="fk_rag_version_document"
        ),
        sa.UniqueConstraint(
            "document_id", "version", name="uq_rag_version_document_version"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_version_document",
        "rag_document_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_rag_document_versions_content_hash",
        "rag_document_versions",
        ["content_hash"],
        unique=False,
    )

    op.create_table(
        "rag_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(32), nullable=False, server_default="section"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("section_title", sa.String(512), nullable=False, server_default=""),
        sa.Column("heading_path", sa.JSON(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("start_char", sa.Integer(), nullable=True),
        sa.Column("end_char", sa.Integer(), nullable=True),
        sa.Column("content_plain", sa.Text(), nullable=False),
        sa.Column("content_tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False, server_default="GENERIC"),
        sa.Column("make", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("year_start", sa.Integer(), nullable=True),
        sa.Column("year_end", sa.Integer(), nullable=True),
        sa.Column("embedding_store", Vector(1024), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["rag_document_versions.id"],
            name="fk_rag_chunk_version",
        ),
        sa.UniqueConstraint(
            "document_version_id", "chunk_index", name="uq_rag_chunk_version_index"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_chunk_version",
        "rag_chunks",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_rag_chunk_scope",
        "rag_chunks",
        ["scope"],
        unique=False,
    )
    op.create_index(
        "ix_rag_chunk_content_tsv",
        "rag_chunks",
        ["content_tsv"],
        unique=False,
        postgresql_using="gin",
    )
    op.execute(
        "CREATE INDEX ix_rag_chunk_embedding ON rag_chunks "
        "USING hnsw (embedding_store vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rag_chunk_embedding")
    op.drop_index("ix_rag_chunk_content_tsv", table_name="rag_chunks")
    op.drop_index("ix_rag_chunk_scope", table_name="rag_chunks")
    op.drop_index("ix_rag_chunk_version", table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_index("ix_rag_document_versions_content_hash", table_name="rag_document_versions")
    op.drop_index("ix_rag_version_document", table_name="rag_document_versions")
    op.drop_table("rag_document_versions")
    op.drop_index("ix_rag_documents_make_model", table_name="rag_documents")
    op.drop_index("ix_rag_documents_manufacturer", table_name="rag_documents")
    op.drop_table("rag_documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
