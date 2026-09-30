"""Phase 5 RAG package (retrieval-augmented evidence layer).

Layout at a glance::

    app/rag/
        config.py        environment-driven RAGSettings (lazy, no model load)
        errors.py        error taxonomy (expected vs unexpected failures)
        schemas.py       public pydantic shapes (evidence, search, health)
        document.py      internal normalized parsed representation
        scope.py         vehicle-scope derivation + tiering
        query_builder.py query expansion / variants
        parser/          document parsers (plain-text, Docling)
        chunking.py      structure-aware chunking
        chunker.py       embeddings / reranker wrappers
        reranker.py
        retrieval.py     hybrid fusion + rerank shortlist + final selection
        repository.py    raw-SQL pgvector/FTS repository
        rag_service.py   orchestration (RAGService)
        ingestion.py     ingestion + versioning
        evaluation.py    offline retrieval evaluation
        diagnostics.py   health/readiness diagnostics

The agent layer consumes ``app.rag.rag_service.RAGService`` (via a thin tool
adapter); the admin API consumes the read-only schemas and diagnostics. No
module here loads model weights or touches the database at import time.
"""

# Import the public, side-effect-free surface eagerly so downstream layers can
# use ``from app.rag import ...`` without walking submodule internals. Model
# weights and embeddings stay lazy behind explicit ``load()`` calls.
from app.rag.errors import RAGUnavailableError
from app.rag.schemas import (
    Citation,
    RAGGuidanceResult,
    RAGHealthResponse,
    RAGSearchResult,
    RetrievedEvidence,
    VehicleScope,
)

__all__ = [
    "Citation",
    "RAGGuidanceResult",
    "RAGHealthResponse",
    "RAGSearchResult",
    "RAGUnavailableError",
    "RetrievedEvidence",
    "VehicleScope",
]
