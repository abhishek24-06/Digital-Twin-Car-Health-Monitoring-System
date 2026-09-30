"""Phase 5 RAG error taxonomy.

Every failure in the RAG layer is a :class:`RAGError` subclass so callers can
discriminate without string-matching. ``RAGUnavailableError`` and its
subclasses represent *expected* degraded states (pgvector missing, model
weights absent, feature disabled) — the Phase 4 agent layer treats those as
"evidence mode unavailable" and degrades to LLM-only behaviour instead of
surfacing a 500.
"""

from __future__ import annotations


class RAGError(Exception):
    """Base class for the Phase 5 RAG error taxonomy."""


class RAGUnavailableError(RAGError):
    """Expected state: the RAG stack cannot serve requests right now.

    Raised when pgvector is missing, model weights are absent, or RAG is
    disabled. Callers treat this as evidence-mode-unavailable and fall back to
    the Phase 4 behaviour.
    """


class RAGEnabledError(RAGError):
    """RAG is disabled by configuration (``RAG_ENABLED=false``)."""


class RAGConfigurationError(RAGError):
    """RAG settings are invalid (e.g. wrong embedding dimension)."""


class RAGVectorUnavailableError(RAGUnavailableError):
    """pgvector is not available in the connected database."""


class RAGParseError(RAGError):
    """A source file could not be parsed into the normalised intermediate.

    Raised by parsers (plain text, Docling) when the input is unreadable,
    unsupported, or structurally unusable. Unlike unavailability errors this is
    an *unexpected* failure for a specific file — it is not a degraded-state
    signal.
    """


class RAGDocumentNotFoundError(RAGError):
    """The requested canonical source document is not in the corpus."""


class RAGDiagnosticsUnavailableError(RAGError):
    """RAG diagnostics could not be produced (corpus probing failed)."""


class RAGRerankerModelUnavailableError(RAGUnavailableError):
    """The reranker weights could not be loaded (matches BGE-bge-reranker)."""


class RAGUnavailableErrorAlias(RAGError):
    """Unused alias kept for import stability during the Phase 5 transition."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message or "RAG unavailable")


class RAGEmbeddingModelUnavailableError(RAGUnavailableError):
    """The embedding model cannot be reached/loaded right now.

    Distinct from a generic connectivity error because Phase 5 treats this as an
    *expected* degraded state (weights absent, model store offline): callers
    report ``embedding_unavailable=true`` in health and keep retrieval going
    with lexical/hybrid evidence rather than raising a 500.
    """

    def __init__(self, message: str = "") -> None:
        super().__init__(message or "RAG embedding model is unavailable")


class RAGUploadError(RAGError):
    """Base class for admin document-upload failures."""


class RAGUploadValidationError(RAGUploadError):
    """The uploaded document failed validation (unsupported/unsafe/empty).

    Mapped to HTTP 400 by the API layer.
    """


class RAGUploadTooLargeError(RAGUploadError):
    """The uploaded document exceeds the configured upload size limit.

    Mapped to HTTP 413 by the API layer.
    """


class RAGIngestionFailureError(RAGError):
    """The existing ingestion pipeline rejected or failed the document.

    Mapped to HTTP 422 by the API layer; nothing is left half-persisted.
    """


class RAGDocumentUnavailableError(RAGError):
    """The RAG corpus cannot serve document management right now.

    Raised when pgvector is unavailable/untable — the admin list/detail/delete
    and upload endpoints degrade to HTTP 503 rather than fabricating results.
    """
