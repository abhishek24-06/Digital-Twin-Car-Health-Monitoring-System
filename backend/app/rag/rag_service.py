"""RAG orchestration: query plan -> embeddings -> hybrid retrieval -> rerank ->
citations/guidance.

``RAGService`` is the single entry point the application (CLI / API / agent)
uses to ask the corpus a question. It wires the pure pieces together:

1. :func:`app.rag.query_builder.build_plan`  — sanitise/expand the query,
2. embedding adapter (real BGE-M3 by default, deterministic stub for tests),
3. :class:`~app.rag.repository.RagRepository.hybrid_search` — dense+lexical legs,
4. :func:`app.rag.retrieval.rerank_and_select` — tiering + BGE reranker + top-k,
5. provenance assembly — ``Citation`` list + verbatim ``RAGGuidanceResult``.

Nothing here loads models or connects at import time; models load lazily on the
first search, and the service pairs with an ``AsyncConnection`` supplied by the
caller (each search runs in the caller's transaction).
"""

from __future__ import annotations

import logging
from typing import Any

from app.rag.config import get_rag_settings
from app.rag.embeddings import EmbeddingAdapter, get_embedding_adapter
from app.rag.errors import RAGEnabledError
from app.rag.query_builder import build_plan
from app.rag.repository import RagRepository
from app.rag.reranker.base import RerankerAdapter, get_reranker_adapter
from app.rag.retrieval import rerank_and_select
from app.rag.schemas import (
    Citation,
    RAGGuidanceResult,
    RAGSearchResult,
    RetrievedEvidence,
    VehicleScope,
)

logger = logging.getLogger(__name__)


class RAGService:
    """Coordinator for one query against the RAG corpus."""

    def __init__(
        self,
        *,
        embedding_adapter: EmbeddingAdapter | None = None,
        reranker_adapter: RerankerAdapter | None = None,
        stub_embeddings: bool = False,
        stub_rerank: bool = False,
        enabled: bool | None = None,
    ) -> None:
        self._embedding = embedding_adapter
        self._reranker = reranker_adapter
        self._stub_embeddings = stub_embeddings
        self._stub_rerank = stub_rerank
        # ``None`` defers to configuration; an explicit boolean lets tests and
        # the agent layer pin behaviour without touching the cached settings.
        self._enabled_override = enabled

    @property
    def rag_enabled(self) -> bool:
        """Effective enabled state (constructor override or configuration)."""
        if self._enabled_override is not None:
            return self._enabled_override
        return get_rag_settings().rag_enabled

    # ----------------------------------------------------------------- model

    def _embedding_adapter(self) -> EmbeddingAdapter:
        if self._embedding is None:
            self._embedding = get_embedding_adapter(force_stub=self._stub_embeddings)
        return self._embedding

    def _reranker_adapter(self) -> RerankerAdapter | None:
        if self._reranker is None:
            # Never raise: the reranker is optional — retrieval works without it.
            try:
                self._reranker = get_reranker_adapter(force_stub=self._stub_rerank)
            except Exception as exc:  # noqa: BLE001 - degraded, not fatal
                logger.warning("reranker unavailable, falling back to hybrid order: %s", exc)
                self._reranker = None
        return self._reranker

    def close(self) -> None:
        """Release model handles (idempotent)."""
        self._embedding = None
        self._reranker = None

    @property
    def embedding_ready(self) -> bool:
        return self._embedding is not None

    # ----------------------------------------------------------------- query

    async def search(
        self,
        conn,
        query: str,
        vehicle_scope: VehicleScope | None = None,
        *,
        top_k: int | None = None,
        rerank: bool = True,
    ) -> RAGGuidanceResult:
        """Answer ``query`` with grounded, cited evidence. No LLM involved."""
        settings = get_rag_settings()
        q = (query or "").strip()
        if not self.rag_enabled:
            raise RAGEnabledError("RAG is disabled by configuration")
        if not q:
            return RAGGuidanceResult(
                query=query or "",
                vehicle_scope=vehicle_scope,
                available=False,
                reason="empty-query",
            )
        if len(q) > settings.rag_query_max_chars:
            q = q[: settings.rag_query_max_chars]

        final_k = top_k or settings.rag_final_top_k
        plan = build_plan(q, scope=None)

        evidence, reranker_used, metrics = await self._retrieve(
            conn,
            plan.text,
            vehicle_scope,
            candidate_k=settings.rag_rerank_top_k,
            final_k=final_k,
            rerank=rerank,
        )

        citations = _build_citations(evidence)
        guidance = _build_guidance(evidence, vehicle_scope, settings.rag_evidence_max_chars)
        metrics.update(
            {
                "query_chars": len(q),
                "vin_detected": plan.detected_vin,
                "lexical_variants": plan.lexical_variants,
                "rerank_used": reranker_used,
            }
        )
        return RAGGuidanceResult(
            query=plan.text,
            vehicle_scope=vehicle_scope,
            guidance=guidance,
            citations=citations,
            evidence=evidence,
            available=bool(evidence),
            reason="hybrid+rerank" if reranker_used else "hybrid",
            metrics=metrics,
        )

    async def search_evidence(
        self,
        conn,
        query: str,
        vehicle_scope: VehicleScope | None = None,
        *,
        top_k: int | None = None,
        rerank: bool = True,
    ) -> RAGSearchResult:
        """Raw evidence list (no guidance assembly) for API/eval consumers."""
        settings = get_rag_settings()
        if not self.rag_enabled:
            raise RAGEnabledError("RAG is disabled by configuration")
        q = (query or "").strip()[: settings.rag_query_max_chars]
        final_k = top_k or settings.rag_final_top_k
        plan = build_plan(q, scope=None)

        evidence, reranker_used, metrics = await self._retrieve(
            conn,
            plan.text,
            vehicle_scope,
            candidate_k=settings.rag_rerank_top_k,
            final_k=final_k,
            rerank=rerank,
        )
        metrics["rerank_used"] = reranker_used
        return RAGSearchResult(
            query=plan.text,
            vehicle_scope=vehicle_scope,
            results=evidence,
            available=bool(evidence),
            reason="hybrid+rerank" if reranker_used else "hybrid",
            metrics=metrics,
        )

    async def _retrieve(
        self,
        conn,
        query_text: str,
        vehicle_scope: VehicleScope | None,
        *,
        candidate_k: int,
        final_k: int,
        rerank: bool,
    ) -> tuple[list[RetrievedEvidence], bool, dict[str, Any]]:
        settings = get_rag_settings()
        alpha = settings.rag_hybrid_alpha
        embedder = self._embedding_adapter()
        vec = embedder.encode([query_text], normalize=True)
        query_vector = vec[0] if len(vec.shape) > 1 else vec

        repo = RagRepository(conn)
        candidates = await repo.hybrid_search(
            query_text, query_vector, top_k=candidate_k, vehicle_scope=vehicle_scope
        )

        reranker = self._reranker_adapter() if rerank else None
        reranker_used = bool(rerank and reranker is not None and candidates)
        evidence = rerank_and_select(
            candidates,
            query_text,
            reranker,
            top_k=final_k,
            min_score=None if reranker_used else 0.0,
            enabled=reranker_used,
            query_scope=vehicle_scope,
        )

        dense_scores = [e.dense_score for e in candidates if e.dense_score is not None]
        lexical_scores = [e.lexical_score for e in candidates if e.lexical_score is not None]
        hybrid_scores = [e.hybrid_score for e in candidates if e.hybrid_score is not None]
        metrics: dict[str, Any] = {
            "alpha": alpha,
            "candidates": len(candidates),
            "dense_leg": {
                "count": len(dense_scores),
                "max": max(dense_scores) if dense_scores else None,
            },
            "lexical_leg": {
                "count": len(lexical_scores),
                "max": max(lexical_scores) if lexical_scores else None,
            },
            "hybrid_leg": {
                "count": len(hybrid_scores),
                "max": max(hybrid_scores) if hybrid_scores else None,
            },
            "scope_filtered": vehicle_scope is not None,
            "embedding_model": embedder.name,
            "reranker_model": reranker.name if reranker else None,
        }
        return evidence, reranker_used, metrics

    async def health(self, conn) -> dict[str, Any]:
        """Adaptor-level diagnostics (no retrieval)."""
        repo = RagRepository(conn)
        db_health = await repo.health()
        embed = self._embedding_adapter()
        reranker = self._reranker_adapter()
        out = {
            "rag_enabled": get_rag_settings().rag_enabled,
            "embedding_adapter": embed.health(),
            "reranker_adapter": reranker.health() if reranker else {"name": None},
        }
        out.update(db_health)
        return out


def _build_citations(evidence: list[RetrievedEvidence]) -> list[Citation]:
    return [
        Citation(
            index=i,
            document_id=e.document_id,
            document_version_id=e.document_version_id,
            document_version=e.document_version,
            chunk_id=e.chunk_id,
            source_filename=e.source_filename,
            title=e.title,
            section_title=e.section_title,
            page_start=e.page_start,
            page_end=e.page_end,
        )
        for i, e in enumerate(evidence, start=1)
    ]


def _build_guidance(
    evidence: list[RetrievedEvidence],
    vehicle_scope: VehicleScope | None,
    max_chars: int,
) -> str:
    """Assemble verbatim, cited guidance lines — no free-form generation."""
    if not evidence:
        return ""
    header = "Grounded manufacturer guidance (verbatim source excerpts):"
    if vehicle_scope and (vehicle_scope.make or vehicle_scope.model or vehicle_scope.year):
        parts = [vehicle_scope.make or "", vehicle_scope.model or "", str(vehicle_scope.year or "")]
        header = f"Grounded manufacturer guidance for {' '.join(p for p in parts if p)}:"
    lines = [header]
    for i, e in enumerate(evidence, start=1):
        snippet = " ".join(e.content.split())
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + "…"
        source = e.source_filename or e.title or "corpus"
        section = f' (section "{e.section_title}")' if e.section_title else ""
        page = ""
        if e.page_start and e.page_end:
            page = f", pages {e.page_start}-{e.page_end}"
        elif e.page_start:
            page = f", page {e.page_start}"
        lines.append(f"[{i}] {snippet} — {source}{section}{page}.")
    return "\n".join(lines)
