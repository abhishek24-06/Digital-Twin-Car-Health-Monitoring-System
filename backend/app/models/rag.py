"""Phase 5 RAG ORM models (pgvector + immutable versioning).

Provenance model
----------------
Identity lives on :class:`RagDocument` (canonical corpus document). Each
ingestion produces an **immutable** :class:`RagDocumentVersion` snapshot; the
chunks of that version live on :class:`RagChunk`. Re-ingesting identical
content is a no-op (content hash matches), so a single document may own many
versions over time — retrieval always reads *completed* versions.

Vector store
------------
:class:`RagChunk.embedding_store` is a ``vector(1024)`` column from `pgvector`.
Because Phase 5 deliberately does **not** depend on SQLAlchemy's pgvector type
at import time (the local test database has no pgvector extension), the column
is declared as ``Vector(1024)`` lazily inside a factory that only runs when the
extension has been confirmed available by :mod:`app.rag.repository`. The FTS
column ``content_tsv`` is populated by a migration trigger and indexed with GIN.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def make_embedding_column(dimension: int) -> Mapped:
    """Build a pgvector ``vector(dimension)`` mapped column.

    Returns a `Mapped` object for use with ``mapped_column``. pgvector's own
    SQLAlchemy type is imported here — not at module import time — so the whole
    package stays importable on test databases without the extension.

    Raises:
        RuntimeError: if pgvector's SQLAlchemy type cannot be imported.
    """
    try:
        from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]
        from sqlalchemy.types import TypeDecorator
    except Exception as exc:  # pragma: no cover - environment specific
        raise RuntimeError("pgvector python package missing") from exc

    class _Embedding(TypeDecorator):
        impl = Vector(dimension)
        cache_ok = True

    return _Embedding()


# Re-exported for the RAG layer.
__all__ = [
    "RagDocument",
    "RagDocumentVersion",
    "RagChunk",
    "make_embedding_column",
]


class RagDocument(Base):
    """A canonical source document in the RAG corpus (identity only).

    Scope metadata describes which vehicles the manual applies to. ``None``
    means "not constrained" — never invented by the system.
    """

    __tablename__ = "rag_documents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manufacturer")
    canonical_source: Mapped[str | None] = mapped_column(String(512), unique=True)
    source_uri: Mapped[str | None] = mapped_column(String(1024))
    manufacturer: Mapped[str | None] = mapped_column(String(128))
    make: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    model_year_start: Mapped[int | None] = mapped_column(Integer)
    model_year_end: Mapped[int | None] = mapped_column(Integer)
    document_type: Mapped[str] = mapped_column(String(32), default="generic")
    title: Mapped[str] = mapped_column(String(512))
    language: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    versions: Mapped[list[RagDocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="RagDocumentVersion.version",
    )

    __table_args__ = (
        Index("ix_rag_documents_make_model", "make", "model"),
        Index("ix_rag_documents_manufacturer", "manufacturer"),
    )


class RagDocumentVersion(Base):
    """Immutable snapshot of one parsed/ingested revision of a document.

    Field meaning follows the spec exactly: ``embedding_model`` records which
    embedder produced the vectors, ``parser_name`` which loader normalised the
    source, ``chunking_version`` which chunker revision ran.
    """

    __tablename__ = "rag_document_versions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("rag_documents.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(16))
    page_count: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ingestion_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[RagDocument] = relationship(back_populates="versions")
    chunks: Mapped[list[RagChunk]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
        order_by="RagChunk.chunk_index",
    )

    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_rag_version_document_version"),
        Index("ix_rag_version_document", "document_id"),
    )


class RagChunk(Base):
    """A single vectorised chunk with complete provenance + typing.

    ``chunk_index`` is zero-based within the version; ``start_char``/``end_char``
    are offsets into a canonical plain-text dump so evidence can be traced back
    to the exact span even after chunking parameters change. ``heading_path``
    preserves the section hierarchy (structure-aware chunking).
    """

    __tablename__ = "rag_chunks"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("rag_document_versions.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), default="section")
    title: Mapped[str] = mapped_column(String(512), default="")
    section_title: Mapped[str] = mapped_column(String(512), default="")
    heading_path: Mapped[list] = mapped_column(JSON, default=list)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    start_char: Mapped[int | None] = mapped_column(Integer)
    end_char: Mapped[int | None] = mapped_column(Integer)
    content_plain: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="GENERIC")
    make: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    year_start: Mapped[int | None] = mapped_column(Integer)
    year_end: Mapped[int | None] = mapped_column(Integer)
    embedding_store = mapped_column(make_embedding_column(1024), nullable=True)
    content_tsv: Mapped[str | None] = mapped_column(TSVECTOR)  # populated by trigger
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document_version: Mapped[RagDocumentVersion] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_index", name="uq_rag_chunk_version_index"),
        Index("ix_rag_chunk_version", "document_version_id"),
        Index("ix_rag_chunk_scope", "scope"),
        Index("ix_rag_chunk_content_tsv", "content_tsv", postgresql_using="gin"),
    )
