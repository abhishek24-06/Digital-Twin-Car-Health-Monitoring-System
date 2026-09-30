"""Response schemas for the Phase 5/6.x RAG admin API.

Phase 6.x adds the admin document-management surface on top of the Phase 5
read-only health/search endpoints. Document identity/version shapes are reused
verbatim from :mod:`app.rag.schemas` (``RAGDocumentSummary`` /
``RAGVersionSummary``) — these wrappers only add the upload/management payloads.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.rag.schemas import RAGDocumentSummary, RAGVersionSummary


class RAGHealthResponse(BaseModel):
    """RAG diagnostics: enabled state, backend availability, corpus counts."""

    rag_enabled: bool
    pgvector_available: bool
    embedding_adapter: dict[str, Any] = Field(default_factory=dict)
    reranker_adapter: dict[str, Any] = Field(default_factory=dict)
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    corpus_documents: int = 0
    corpus_versions: int = 0
    corpus_completed_chunks: int = 0


UploadStatus = Literal["ingested", "unchanged"]


class AdminRagDocumentUploadForm(BaseModel):
    """Multipart metadata for an admin document upload.

    Mirrors the existing ingestion kwargs — no invented metadata concepts. The
    extra fields (manufacturer, document_type, language, …) are reused from the
    Phase 5 ``IngestionService.ingest`` signature.
    """

    canonical: str = Field(
        min_length=1,
        max_length=512,
        description="Canonical identity, e.g. rep://toyota/camry/2024/service-manual",
    )
    make: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    year: int | None = Field(default=None, ge=1900, le=2100)
    manufacturer: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=512)
    source_uri: str | None = Field(default=None, max_length=1024)
    source_type: str | None = Field(default=None, max_length=32)
    document_type: str | None = Field(default=None, max_length=32)
    year_end: int | None = Field(default=None, ge=1900, le=2100)
    language: str | None = Field(default=None, max_length=16)

    model_config = ConfigDict(extra="forbid")


class AdminRagUploadResponse(BaseModel):
    """Outcome of one admin upload, using the existing ingestion semantics.

    ``status`` is ``ingested`` (a new document/version was persisted) or
    ``unchanged`` (identical content already completed — Phase 5 idempotency).
    A failed ingestion raises instead of returning a fabricated success.
    """

    id: UUID | None = None
    status: UploadStatus
    filename: str
    canonical: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    version: int | None = None
    chunks_created: int = 0
    content_hash: str = ""
    parser_name: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None


class AdminRagDocumentDetailResponse(RAGDocumentSummary):
    """One document plus its immutable version history (each with chunk count)."""

    versions: list[RAGVersionSummary] = Field(default_factory=list)
    latest_version: RAGVersionSummary | None = None
