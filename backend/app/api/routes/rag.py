"""Read-only RAG admin API (Phase 5).

Two resources, both read-only and consistent with the CLI-first design:

* ``GET /api/v1/rag/health`` — diagnostics: enabled state, pgvector
  availability, adapter identities, corpus counts. Never loads weights.
* ``GET /api/v1/rag/search`` — evidence search with optional vehicle scope.
  Returns raw retrieved evidence with provenance; no LLM, no mutation.

Degraded states are explicit: RAG disabled or missing pgvector surfaces as a
503 with a stable detail string — never a fabricated empty result being treated
as truth.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user, require_admin
from app.dependencies.database import get_db, get_rag_service
from app.models.user import User
from app.rag.rag_service import RAGService
from app.rag.schemas import RAGSearchResult, VehicleScope
from app.schemas.rag import RAGHealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=RAGHealthResponse,
    summary="RAG diagnostics (read-only, admin)",
    description="Enabled state, pgvector availability, adapter identities, corpus counts.",
)
async def rag_health(
    session: Annotated[AsyncSession, Depends(get_db)],
    rag: Annotated[RAGService, Depends(get_rag_service)],
    user: Annotated[User, Depends(require_admin)],
) -> RAGHealthResponse:
    conn = await session.connection()
    payload = await rag.health(conn)
    return _to_health_response(payload)


@router.get(
    "/search",
    response_model=RAGSearchResult,
    summary="Search the manufacturer corpus (read-only)",
    description="Retrieve evidence with provenance. Optional vehicle scope "
    "filters the corpus (make/model/year). No LLM involved.",
)
async def rag_search(
    session: Annotated[AsyncSession, Depends(get_db)],
    rag: Annotated[RAGService, Depends(get_rag_service)],
    user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str, Query(min_length=1, max_length=500, description="Search query")],
    make: Annotated[str | None, Query(max_length=64)] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
    year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    top_k: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> RAGSearchResult:
    if not rag.rag_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG is disabled by configuration",
        )
    scope = VehicleScope(make=make, model=model, year=year)
    conn = await session.connection()
    try:
        result = await rag.search_evidence(conn, q, vehicle_scope=_nulled(scope), top_k=top_k)
    except Exception:  # noqa: BLE001 - degraded state is explicit
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG backend unavailable (pgvector or model weights missing)",
        ) from None
    return result


def _nulled(scope: VehicleScope) -> VehicleScope:
    """Collapse empty-string query params to ``None`` for honest scoping."""
    return VehicleScope(
        make=scope.make or None,
        model=scope.model or None,
        year=scope.year,
    )


def _to_health_response(payload: dict[str, Any]) -> RAGHealthResponse:
    corpus = payload.get("corpus") or {}
    embed = payload.get("embedding_adapter") or {}
    rerank = payload.get("reranker_adapter") or {}
    return RAGHealthResponse(
        rag_enabled=bool(payload.get("rag_enabled")),
        pgvector_available=bool(payload.get("pgvector_available")),
        embedding_adapter=embed,
        reranker_adapter=rerank,
        embedding_model=embed.get("adapter"),
        embedding_dimension=embed.get("dimension"),
        corpus_documents=int(corpus.get("documents") or 0),
        corpus_versions=int(corpus.get("versions") or 0),
        corpus_completed_chunks=int(corpus.get("completed_chunks") or 0),
    )
