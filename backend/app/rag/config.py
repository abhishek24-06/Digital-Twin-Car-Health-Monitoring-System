"""Phase 5 RAG configuration (environment-driven, lazy).

Settings are loaded through pydantic-settings using the same ``RAG_*``
variables the rest of the application honours. Reading the settings object
never touches model weights or the database, so the Phase 4 layer can import
this module unconditionally.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAG_EMBEDDING_DIMENSION = 1024

DEFAULT_DOCUMENT_ROOTS = ("data/documents",)


class RAGSettings(BaseSettings):
    """RAG/retrieval settings.

    ``RAG_ENABLED`` is the only behavioural gate — every other field has a
    documented default so a bare instance is always usable for offline
    evaluation without an active corpus.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    rag_enabled: bool = True

    # Embedding model (BGE-M3). Dimension is fixed by pgvector declaration.
    rag_embedding_model: str = "BAAI/bge-m3"
    rag_embedding_dimension: int = RAG_EMBEDDING_DIMENSION
    rag_embedding_device: str = "auto"
    rag_embedding_batch_size: int = 16
    rag_embedding_max_length: int = 1024
    rag_embedding_normalize: bool = True

    # Reranker (BGE cross-encoder).
    rag_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rag_reranker_device: str = "auto"
    rag_reranker_max_length: int = 512

    # Chunking.
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 120

    # Retrieval.
    rag_retrieval_top_k: int = 25
    rag_rerank_top_k: int = 30
    rag_final_top_k: int = 5
    rag_hybrid_alpha: float = 0.6
    rag_min_rerank_score: float = 0.2
    rag_min_score: float = 0.0

    # Ingestion limits / safety.
    rag_max_document_bytes: int = 50 * 1024 * 1024
    rag_max_document_pages: int = 2000
    rag_max_chunks: int = 20_000
    rag_document_roots: tuple[str, ...] = DEFAULT_DOCUMENT_ROOTS

    # Admin document upload (Phase 6.x). Independent of rag_max_document_bytes
    # so the API gateway can enforce a tighter limit than the parser's internal
    # guard; defaults match the ingest limit.
    rag_max_upload_size_mb: int = 50

    # Query / evidence bounds.
    rag_query_max_chars: int = 500
    rag_evidence_max_chars: int = 1800

    @field_validator("rag_hybrid_alpha")
    @classmethod
    def _alpha_in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("rag_hybrid_alpha must be within [0, 1]")
        return value

    @field_validator("rag_min_rerank_score", "rag_min_score")
    @classmethod
    def _min_score_in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("min scores must be within [0, 1]")
        return value

    @field_validator("rag_max_upload_size_mb")
    @classmethod
    def _upload_size_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("rag_max_upload_size_mb must be >= 1")
        return value

    @property
    def rag_max_upload_bytes(self) -> int:
        """Byte equivalent of ``rag_max_upload_size_mb`` for stream checks."""
        return self.rag_max_upload_size_mb * 1024 * 1024

    @field_validator("rag_chunk_overlap")
    @classmethod
    def _overlap_not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("rag_chunk_overlap must be >= 0")
        return value


@lru_cache
def get_rag_settings() -> RAGSettings:
    """Return the process-wide cached :class:`RAGSettings` instance."""
    return RAGSettings()
