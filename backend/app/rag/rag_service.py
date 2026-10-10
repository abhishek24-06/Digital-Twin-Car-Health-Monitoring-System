"""RAG orchestration: query plan -> embeddings -> hybrid retrieval -> rerank ->
citations/guidance.

``RAGService`` is the single entry point the application (CLI / API / agent)
uses to ask the corpus a question. It wires the pure pieces together:

1. :func:`app.rag.query_builder.build_plan`  ? sanitise/expand the query,
2. embedding adapter (real BGE-M3 by default, deterministic stub for tests),
3. :class:`~app.rag.repository.RagRepository.hybrid_search` ? dense+lexical legs,
4. :func:`app.rag.retrieval.rerank_and_select` ? tiering + BGE reranker + top-k,
5. provenance assembly ? ``Citation`` list + verbatim ``RAGGuidanceResult``.

Nothing here loads models or connects at import time; models load lazily on the
first search, and the service pairs with an ``AsyncConnection`` supplied by the
caller (each search runs in the caller's transaction).
"""

from __future__ import annotations

import logging
import time
import uuid
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
from app.schemas.workflow import (
    WorkflowStage,
    WorkflowStatus,
    WorkflowType,
    new_correlation_id,
    sanitize_metadata,
)
from app.services.workflow_event_bus import publish_workflow_event

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
            # Never raise: the reranker is optional ? retrieval works without it.
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

        correlation_id = f"rag-query-{uuid.uuid4().hex[:8]}"

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.QUERY_RECEIVED,
            status=WorkflowStatus.STARTED,
            message=f"RAG query received: {q[:50]}...",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "query_length": len(q),
                    "vehicle_scope": vehicle_scope.__dict__ if vehicle_scope else None,
                    "top_k": top_k,
                    "rerank": rerank,
                }
            ),
        )

        final_k = top_k or settings.rag_final_top_k
        plan = build_plan(q, scope=None)

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.QUERY_EMBEDDING_STARTED,
            status=WorkflowStatus.RUNNING,
            message="Generating query embedding",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "query_chars": len(q),
                }
            ),
        )

        start_time = time.perf_counter()
        embedder = self._embedding_adapter()
        vec = embedder.encode([q], normalize=True)
        query_vector = vec[0] if len(vec.shape) > 1 else vec
        embedding_duration_ms = (time.perf_counter() - start_time) * 1000

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.QUERY_EMBEDDING_COMPLETED,
            status=WorkflowStatus.SUCCESS,
            message="Query embedding generated",
            duration_ms=embedding_duration_ms,
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "embedding_model": embedder.name,
                    "dimensions": embedder.dimension,
                }
            ),
        )

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.VECTOR_SEARCH_STARTED,
            status=WorkflowStatus.RUNNING,
            message="Starting vector search",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "candidate_k": settings.rag_rerank_top_k,
                    "alpha": settings.rag_hybrid_alpha,
                }
            ),
        )

        repo = RagRepository(conn)
        search_start = time.perf_counter()
        candidates = await repo.hybrid_search(
            q, query_vector, top_k=settings.rag_rerank_top_k, vehicle_scope=vehicle_scope
        )
        search_duration_ms = (time.perf_counter() - search_start) * 1000

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.VECTOR_SEARCH_COMPLETED,
            status=WorkflowStatus.SUCCESS,
            message=f"Vector search completed: {len(candidates)} candidates",
            duration_ms=search_duration_ms,
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "candidates": len(candidates),
                    "alpha": settings.rag_hybrid_alpha,
                }
            ),
        )

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.CANDIDATES_RETRIEVED,
            status=WorkflowStatus.SUCCESS,
            message=f"Retrieved {len(candidates)} candidates",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "candidates": len(candidates),
                }
            ),
        )

        reranker = self._reranker_adapter() if rerank else None
        reranker_used = bool(rerank and reranker is not None and candidates)

        if reranker_used:
            await publish_workflow_event(
                workflow=WorkflowType.RAG_QUERY,
                stage=WorkflowStage.RERANKING_STARTED,
                status=WorkflowStatus.RUNNING,
                message=f"Starting reranking with {reranker.name}",
                correlation_id=correlation_id,
                metadata=sanitize_metadata(
                    {
                        "reranker_model": reranker.name,
                        "candidates": len(candidates),
                    }
                ),
            )

        rerank_start = time.perf_counter()
        evidence = rerank_and_select(
            candidates,
            q,
            reranker,
            top_k=final_k,
            min_score=None if reranker_used else 0.0,
            enabled=reranker_used,
            query_scope=vehicle_scope,
        )
        rerank_duration_ms = (time.perf_counter() - rerank_start) * 1000

        if reranker_used:
            await publish_workflow_event(
                workflow=WorkflowType.RAG_QUERY,
                stage=WorkflowStage.RERANKING_COMPLETED,
                status=WorkflowStatus.SUCCESS,
                message=f"Reranking completed: {len(evidence)} results",
                duration_ms=rerank_duration_ms,
                correlation_id=correlation_id,
                metadata=sanitize_metadata(
                    {
                        "reranker_model": reranker.name,
                        "final_count": len(evidence),
                    }
                ),
            )

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.CONTEXT_ASSEMBLED,
            status=WorkflowStatus.SUCCESS,
            message=f"Context assembled from {len(evidence)} evidence items",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "evidence_count": len(evidence),
                    "total_chars": sum(len(e.content) for e in evidence),
                }
            ),
        )

        citations = _build_citations(evidence)
        guidance = _build_guidance(evidence, vehicle_scope, settings.rag_evidence_max_chars)

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.ANSWER_GENERATION_STARTED,
            status=WorkflowStatus.RUNNING,
            message=f"Assembling guidance from {len(evidence)} sources",
            correlation_id=correlation_id,
        )

        start_total = time.perf_counter()
        # The actual guidance is built synchronously in _build_guidance
        guidance_duration_ms = (time.perf_counter() - start_total) * 1000

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.ANSWER_GENERATED,
            status=WorkflowStatus.SUCCESS,
            message=f"Guidance generated from {len(evidence)} sources",
            duration_ms=guidance_duration_ms,
            correlation_id=correlation_id,
        )

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.SOURCES_ATTACHED,
            status=WorkflowStatus.SUCCESS,
            message=f"Attached {len(citations)} source citations",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "citation_count": len(citations),
                    "sources": [c.source_filename for c in citations],
                }
            ),
        )

        metrics = {
            "query_chars": len(q),
            "vin_detected": plan.detected_vin,
            "lexical_variants": plan.lexical_variants,
            "rerank_used": reranker_used,
        }

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.RAG_QUERY_COMPLETED,
            status=WorkflowStatus.SUCCESS,
            message=f"RAG query completed: {len(evidence)} evidence items",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "total_duration_ms": (time.perf_counter() - search_start) * 1000,
                    "evidence_count": len(evidence),
                    "citation_count": len(citations),
                }
            ),
        )

        dense_scores = [e.dense_score for e in candidates if e.dense_score is not None]
        lexical_scores = [e.lexical_score for e in candidates if e.lexical_score is not None]
        hybrid_scores = [e.hybrid_score for e in candidates if e.hybrid_score is not None]
        metrics.update(
            {
                "alpha": settings.rag_hybrid_alpha,
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
        """Raw evidence list (no guidance assembly) for API/eval consumers.

        This is the RAG Query page path (``GET /rag/search``). ``search()`` is
        the agent tool path and keeps its own separate instrumentation.
        """
        settings = get_rag_settings()
        if not self.rag_enabled:
            raise RAGEnabledError("RAG is disabled by configuration")
        q = (query or "").strip()[: settings.rag_query_max_chars]
        final_k = top_k or settings.rag_final_top_k
        plan = build_plan(q, scope=None)
        correlation_id = new_correlation_id("rag-query")

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.QUERY_RECEIVED,
            status=WorkflowStatus.STARTED,
            message=f"RAG query received: {plan.text[:50]}...",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "query_length": len(plan.text),
                    "vehicle_scope": vehicle_scope.__dict__ if vehicle_scope else None,
                    "top_k": top_k,
                    "rerank": rerank,
                }
            ),
        )

        try:
            evidence, reranker_used, metrics = await self._retrieve(
                conn,
                plan.text,
                vehicle_scope,
                candidate_k=settings.rag_rerank_top_k,
                final_k=final_k,
                rerank=rerank,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            await publish_workflow_event(
                workflow=WorkflowType.RAG_QUERY,
                stage=WorkflowStage.RAG_QUERY_ERROR,
                status=WorkflowStatus.ERROR,
                message=f"RAG query failed: {exc}",
                correlation_id=correlation_id,
                metadata=sanitize_metadata({"error": str(exc)}),
            )
            raise

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.CONTEXT_ASSEMBLED,
            status=WorkflowStatus.SUCCESS,
            message=f"Context assembled from {len(evidence)} evidence items",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "evidence_count": len(evidence),
                    "total_chars": sum(len(e.content) for e in evidence),
                }
            ),
        )
        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.RAG_QUERY_COMPLETED,
            status=WorkflowStatus.SUCCESS,
            message=f"RAG query completed: {len(evidence)} evidence items",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "evidence_count": len(evidence),
                }
            ),
        )

        metrics["rerank_used"] = reranker_used
        return RAGSearchResult(
            query=plan.text,
            vehicle_scope=vehicle_scope,
            results=evidence,
            available=bool(evidence),
            reason="hybrid+rerank" if reranker_used else "hybrid",
            metrics=metrics,
            correlation_id=correlation_id,
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
        correlation_id: str | None = None,
    ) -> tuple[list[RetrievedEvidence], bool, dict[str, Any]]:
        settings = get_rag_settings()
        alpha = settings.rag_hybrid_alpha

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.QUERY_EMBEDDING_STARTED,
            status=WorkflowStatus.RUNNING,
            message="Generating query embedding",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "query_chars": len(query_text),
                }
            ),
        )
        start_time = time.perf_counter()
        embedder = self._embedding_adapter()
        vec = embedder.encode([query_text], normalize=True)
        query_vector = vec[0] if len(vec.shape) > 1 else vec
        embedding_duration_ms = (time.perf_counter() - start_time) * 1000
        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.QUERY_EMBEDDING_COMPLETED,
            status=WorkflowStatus.SUCCESS,
            message="Query embedding generated",
            duration_ms=embedding_duration_ms,
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "embedding_model": embedder.name,
                    "dimensions": embedder.dimension,
                }
            ),
        )

        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.VECTOR_SEARCH_STARTED,
            status=WorkflowStatus.RUNNING,
            message="Starting vector search",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "candidate_k": candidate_k,
                    "alpha": alpha,
                }
            ),
        )
        repo = RagRepository(conn)
        search_start = time.perf_counter()
        candidates = await repo.hybrid_search(
            query_text, query_vector, top_k=candidate_k, vehicle_scope=vehicle_scope
        )
        search_duration_ms = (time.perf_counter() - search_start) * 1000
        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.VECTOR_SEARCH_COMPLETED,
            status=WorkflowStatus.SUCCESS,
            message=f"Vector search completed: {len(candidates)} candidates",
            duration_ms=search_duration_ms,
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "candidates": len(candidates),
                    "alpha": alpha,
                }
            ),
        )
        await publish_workflow_event(
            workflow=WorkflowType.RAG_QUERY,
            stage=WorkflowStage.CANDIDATES_RETRIEVED,
            status=WorkflowStatus.SUCCESS,
            message=f"Retrieved {len(candidates)} candidates",
            correlation_id=correlation_id,
            metadata=sanitize_metadata(
                {
                    "candidates": len(candidates),
                }
            ),
        )

        reranker = self._reranker_adapter() if rerank else None
        reranker_used = bool(rerank and reranker is not None and candidates)
        if reranker_used:
            await publish_workflow_event(
                workflow=WorkflowType.RAG_QUERY,
                stage=WorkflowStage.RERANKING_STARTED,
                status=WorkflowStatus.RUNNING,
                message=f"Starting reranking with {reranker.name}",
                correlation_id=correlation_id,
                metadata=sanitize_metadata(
                    {
                        "reranker_model": reranker.name,
                        "candidates": len(candidates),
                    }
                ),
            )

        rerank_start = time.perf_counter()
        evidence = rerank_and_select(
            candidates,
            query_text,
            reranker,
            top_k=final_k,
            min_score=None if reranker_used else 0.0,
            enabled=reranker_used,
            query_scope=vehicle_scope,
        )
        rerank_duration_ms = (time.perf_counter() - rerank_start) * 1000
        if reranker_used:
            await publish_workflow_event(
                workflow=WorkflowType.RAG_QUERY,
                stage=WorkflowStage.RERANKING_COMPLETED,
                status=WorkflowStatus.SUCCESS,
                message=f"Reranking completed: {len(evidence)} results",
                duration_ms=rerank_duration_ms,
                correlation_id=correlation_id,
                metadata=sanitize_metadata(
                    {
                        "reranker_model": reranker.name,
                        "final_count": len(evidence),
                    }
                ),
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
    """Assemble verbatim, cited guidance lines ? no free-form generation."""
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
            snippet = snippet[:max_chars].rstrip() + "???"
        source = e.source_filename or e.title or "corpus"
        section = f' (section "{e.section_title}")' if e.section_title else ""
        page = ""
        if e.page_start and e.page_end:
            page = f", pages {e.page_start}-{e.page_end}"
        elif e.page_start:
            page = f", page {e.page_start}"
        lines.append(f"[{i}] {snippet} ? {source}{section}{page}.")
    return "\n".join(lines)
