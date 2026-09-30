"""Phase 5 CLI: query the RAG corpus with dense+lexical hybrid retrieval,
BGE reranking, and cited, evidence-grounded guidance.

Usage (from the ``backend`` directory)::

    python scripts/query_rag.py "What should be checked when coolant temperature is high?" \\
        --make Toyota --model Camry --year 2024 --top-k 3

Real BGE-M3 embeddings + BGE reranker are used by default; ``--stub`` switches
to the deterministic test adapters. Prints the guidance, citations, and the
full scoring trail for each evidence item.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.rag.embeddings import RAGEmbeddingModelUnavailableError
from app.rag.rag_service import RAGService
from app.rag.schemas import VehicleScope


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the RAG corpus")
    parser.add_argument("query")
    parser.add_argument("--make", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="use deterministic stub embedder + reranker (tests/eval)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def _evidence_dict(e: Any) -> dict[str, Any]:
    return {
        "chunk_id": str(e.chunk_id),
        "document_id": str(e.document_id),
        "document_version": e.document_version,
        "source": e.source_filename,
        "title": e.title,
        "section": e.section_title,
        "pages": [e.page_start, e.page_end],
        "dense": e.dense_score,
        "lexical": e.lexical_score,
        "hybrid": e.hybrid_score,
        "rerank": e.rerank_score,
        "citation": e.rerank_score is not None,
        "content_excerpt": " ".join(e.content.split())[:400],
    }


async def _main(args: argparse.Namespace) -> int:
    engine = None
    try:
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        service = RAGService(stub_embeddings=args.stub, stub_rerank=args.stub)
        scope = VehicleScope(make=args.make, model=args.model, year=args.year)
        async with engine.connect() as conn:
            try:
                result = await service.search(
                    conn, args.query, scope, top_k=args.top_k, rerank=not args.no_rerank
                )
            except RAGEmbeddingModelUnavailableError as exc:
                print(f"EMBEDDING_UNAVAILABLE: {exc}", file=sys.stderr)
                return 2

            if args.json:
                payload = {
                    "query": result.query,
                    "available": result.available,
                    "reason": result.reason,
                    "metrics": result.metrics,
                    "guidance": result.guidance,
                    "citations": [c.model_dump(mode="json") for c in result.citations],
                    "evidence": [_evidence_dict(e) for e in result.evidence],
                }
                print(json.dumps(payload, indent=2))
                return 0

            print(result.guidance)
            print("\nCitations:")
            for c in result.citations:
                page = f"p.{c.page_start}-{c.page_end}" if c.page_start and c.page_end else "p.?-?"
                sec = f'"{c.section_title}"' if c.section_title else "(no section)"
                print(
                    f"  [{c.index}] {c.title or c.source_filename} — {sec}, {page}, "
                    f"version {c.document_version}"
                )
            print("\nEvidence trail:")
            for e in result.evidence:
                print(
                    f"  dense={e.dense_score:.4f} lexical={e.lexical_score:.4f} "
                    f"hybrid={e.hybrid_score:.4f} rerank={e.rerank_score if e.rerank_score is not None else '—':}\n"
                    f"    {e.section_title} ({e.source_filename}) "
                    f"pages {e.page_start}-{e.page_end} | reranked={e.rerank_score is not None}"
                )
            print("\nMetrics:", json.dumps(result.metrics))
        return 0
    finally:
        if engine is not None:
            await engine.dispose()
            service.close()


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
