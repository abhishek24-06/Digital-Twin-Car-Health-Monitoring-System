"""Public API schemas for the Phase 5 RAG corpus.

These are the read-only shapes the admin API and retrieval results expose. The
distinguishing feature of the Phase 5 design is *complete provenance*: every
retrieved chunk carries the document, the immutable version it came from, the
page range, the section, and the full dense/lexical/hybrid/rerank scoring
trail so evidence can be audited and evaluation results replayed deterministically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ScopeTier = Literal["EXACT_VEHICLE", "MODEL", "MAKE", "GENERIC"]

SCOPE_TIERS: dict[str, int] = {
    "GENERIC": 0,
    "MAKE": 1,
    "MODEL": 2,
    "EXACT_VEHICLE": 3,
}


class VehicleScope(BaseModel):
    """Vehicle identity used to scope/filter retrieved evidence.

    All fields stay ``None`` when unknown — nothing is ever invented or
    guessed by the retrieval layer.
    """

    make: str | None = None
    model: str | None = None
    year: int | None = None
    engine: str | None = None
    region: str | None = None


class RetrievedEvidence(BaseModel):
    """One retrieved chunk with provenance and the full scoring trail."""

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_version: int
    title: str = ""
    manufacturer: str | None = None
    make: str | None = None
    model: str | None = None
    model_year_start: int | None = None
    model_year_end: int | None = None
    document_type: str = "generic"
    source_filename: str | None = None
    section_title: str = ""
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    content: str = ""
    scope: ScopeTier = "GENERIC"
    dense_score: float | None = None
    lexical_score: float | None = None
    hybrid_score: float | None = None
    rerank_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RAGSearchResult(BaseModel):
    """Structured retrieval result (no LLM involved — pure evidence)."""

    query: str
    vehicle_scope: VehicleScope | None = None
    results: list[RetrievedEvidence] = Field(default_factory=list)
    available: bool = False
    reason: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class RAGDocumentSummary(BaseModel):
    """Read-only admin view of one document in the corpus."""

    id: UUID
    source_type: str
    canonical_source: str | None = None
    source_uri: str | None = None
    manufacturer: str | None = None
    make: str | None = None
    model: str | None = None
    model_year_start: int | None = None
    model_year_end: int | None = None
    document_type: str
    title: str
    language: str | None = None
    created_at: datetime
    updated_at: datetime
    version_count: int = 0


class RAGVersionSummary(BaseModel):
    """Read-only admin view of one immutable document version."""

    id: UUID
    document_id: UUID
    version: int
    content_hash: str
    source_filename: str
    parser_name: str
    parser_version: str | None = None
    language: str | None = None
    page_count: int | None = None
    embedding_model: str
    embedding_dimension: int
    chunking_version: str
    ingestion_status: str
    error_message: str | None = None
    created_at: datetime
    chunk_count: int = 0


class Citation(BaseModel):
    """One grounded citation: which chunk of which immutable version backs it."""

    index: int
    document_id: UUID
    document_version_id: UUID
    document_version: int
    chunk_id: UUID
    source_filename: str | None = None
    title: str = ""
    section_title: str = ""
    page_start: int | None = None
    page_end: int | None = None


class RAGGuidanceResult(BaseModel):
    """Evidence-grounded manufacturer guidance for one query.

    ``guidance`` is assembled strictly from verbatim retrieved chunk content
    with ``[n]`` citation markers — never free-form generation (no LLM in this
    pipeline). Every claim maps to a :class:`Citation` with full provenance.
    """

    query: str
    vehicle_scope: VehicleScope | None = None
    guidance: str = ""
    citations: list[Citation] = Field(default_factory=list)
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    available: bool = False
    reason: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class RAGHealthResponse(BaseModel):
    """RAG diagnostics: enabled state, backend availability, corpus counts."""

    rag_enabled: bool
    pgvector_available: bool
    embedding_model: str
    embedding_dimension: int
    reranker_model: str
    document_count: int
    document_version_count: int
    completed_chunk_count: int
    documents_directory: list[str]
