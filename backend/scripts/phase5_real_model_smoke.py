"""Phase 5 REAL-MODEL smoke: Docling-free sample through BGE-M3 + pgvector +
BGE-reranker with real weights.

This script is the anti-fake gate. It refuses to swallow model-load failures:
``--check-only`` loads BGE-M3 + reranker and encodes/scans a fixed prompt, and
the full run ingests the Camry cooling sample with *real* embeddings, searches
with *real* reranking, and cleans up afterwards.

Exit codes:
    0  PASSED (or check-only ok)
    2  embedding model unavailable / encode failure
    3  reranker unavailable / rerank failure
    4  database round-trip assertion failed
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.rag.embeddings import RAGEmbeddingModelUnavailableError
from app.rag.ingestion import IngestionService
from app.rag.rag_service import RAGService
from app.rag.reranker.base import RAGRerankerModelUnavailableError
from app.rag.schemas import VehicleScope

_SAMPLE_NAME = "toyota_camry_2024_cooling.md"
_SAMPLE_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "data" / "documents" / _SAMPLE_NAME,
    Path(__file__).resolve().parents[2] / "data" / "documents" / _SAMPLE_NAME,
]
SAMPLE = next((p for p in _SAMPLE_CANDIDATES if p.exists()), _SAMPLE_CANDIDATES[0])
QUERY = "What should be checked when coolant temperature is high?"


async def check_only() -> None:
    from app.rag.embeddings import get_embedding_adapter
    from app.rag.reranker.base import get_reranker_adapter

    embedder = get_embedding_adapter(force_stub=False)
    vec = embedder.encode(["coolant temperature high"], normalize=True)
    print(f"EMBED_OK model={embedder.name} dim={embedder.dimension} shape={vec.shape}")
    if vec.shape[1] != 1024:
        print("FAILED: embedding dimension != 1024", file=sys.stderr)
        raise SystemExit(4)

    reranker = get_reranker_adapter(force_stub=False)
    scores = reranker.rerank(
        "coolant temperature high",
        ["check coolant level in the reservoir", "brake pad wear measurement procedure"],
    )
    print(f"RERANK_OK model={reranker.name} scores={[round(s, 4) for s in scores]}")
    if not all(0.0 <= s <= 1.0 for s in scores):
        print("WARN: rerank scores outside [0,1]; check activation_fn", file=sys.stderr)


async def full_roundtrip(keep: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    canonical = f"smoke://camry-2024-real-{uuid4().hex[:8]}"
    service = RAGService(stub_embeddings=False, stub_rerank=False)
    ingest = IngestionService(stub_embeddings=False)
    try:
        async with engine.connect() as conn:
            report = await ingest.ingest(
                conn,
                SAMPLE,
                canonical_source=canonical,
                title="Toyota Camry 2024 Cooling (real-model smoke)",
                manufacturer="Toyota",
                make="Toyota",
                model="Camry",
                year_start=2024,
                year_end=2024,
            )
            if report.status != "ingested":
                print(f"INGEST_FAILED: {report.error}", file=sys.stderr)
                return 4
            print(
                f"INGEST_OK doc={report.document_id} version={report.version} "
                f"chunks={report.chunk_count} model={report.embedding_model}"
            )

            result = await service.search(
                conn,
                QUERY,
                VehicleScope(make="Toyota", model="Camry", year=2024),
                top_k=3,
                rerank=True,
            )
            print(f"SEARCH_OK available={result.available} reason={result.reason}")
            print(result.guidance)
            print("METRICS:", result.metrics)
            if not result.evidence:
                print("FAILED: no evidence returned", file=sys.stderr)
                return 4
            top = result.evidence[0]
            print(
                f"TOP dense={top.dense_score:.4f} lexical={top.lexical_score:.4f} "
                f"hybrid={top.hybrid_score:.4f} rerank={top.rerank_score:.4f} "
                f"section={top.section_title!r}"
            )
            if result.metrics.get("embedding_model") != "bge-m3":
                print("FAILED: expected real bge-m3 embedding model", file=sys.stderr)
                return 4
            if top.rerank_score is None:
                print("FAILED: real reranker did not produce scores", file=sys.stderr)
                return 4

            if not keep:
                from sqlalchemy import text

                await conn.execute(
                    text("delete from rag_chunks where document_version_id = :v"),
                    {"v": report.version_id},
                )
                await conn.execute(
                    text("delete from rag_document_versions where id = :v"),
                    {"v": report.version_id},
                )
                await conn.execute(
                    text("delete from rag_documents where id = :d"),
                    {"d": report.document_id},
                )
                print("CLEANUP_OK")
        return 0
    except RAGEmbeddingModelUnavailableError as exc:
        print(f"EMBEDDING_UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    except RAGRerankerModelUnavailableError as exc:
        print(f"RERANKER_UNAVAILABLE: {exc}", file=sys.stderr)
        return 3
    finally:
        await engine.dispose()
        service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 real-model smoke")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="load models and verify dims/scores without the database",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the smoke document in the corpus (default: delete)",
    )
    args = parser.parse_args()
    if args.check_only:
        raise SystemExit(asyncio.run(check_only()))
    raise SystemExit(asyncio.run(full_roundtrip(args.keep)))


if __name__ == "__main__":
    main()
