"""Phase 5 CLI: ingest one or more manufacturer documents into the RAG corpus.

Usage (from the ``backend`` directory)::

    python scripts/ingest_documents.py "data/documents/toyota_camry_2024_cooling.md" \
        --make Toyota --model Camry --year 2024 --stub-embeddings

Connects through the application settings (``DATABASE_URL``), so the intake
target is whatever the app is configured for (production: Supabase pgvector).

Exit code 0 = every file ingested; 1 = at least one file failed.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.rag.ingestion import IngestionService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest documents into the RAG corpus")
    parser.add_argument("paths", nargs="+", type=Path, help="source files (.pdf/.docx/.md/.txt …)")
    parser.add_argument(
        "--canonical",
        action="append",
        default=None,
        help="canonical_source override (repeat per file; default: file stem)",
    )
    parser.add_argument("--uri", help="source URI (repeatable? use --canonical for pairing)")
    parser.add_argument("--title", action="append", default=None, help="document title per file")
    parser.add_argument("--manufacturer", default="Toyota")
    parser.add_argument("--make", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--year-end", type=int, default=None)
    parser.add_argument("--source-type", default="manufacturer")
    parser.add_argument("--document-type", default="service-manual")
    parser.add_argument("--language", default="en")
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-overlap", type=int, default=None)
    parser.add_argument(
        "--stub-embeddings",
        action="store_true",
        help="use the deterministic stub embedder (tests/eval only)",
    )
    return parser


async def _main(args: argparse.Namespace) -> int:
    engine = None
    try:
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        service = IngestionService(
            stub_embeddings=args.stub_embeddings,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
        failures = 0
        async with engine.connect() as conn:
            for i, path in enumerate(args.paths):
                canonical = (
                    args.canonical[i] if args.canonical and i < len(args.canonical) else path.stem
                )
                title = args.title[i] if args.title and i < len(args.title) else path.stem
                report = await service.ingest(
                    conn,
                    path,
                    canonical_source=canonical,
                    title=title,
                    source_uri=args.uri,
                    source_type=args.source_type,
                    manufacturer=args.manufacturer,
                    make=args.make,
                    model=args.model,
                    year_start=args.year,
                    year_end=args.year_end
                    or (args.year if args.year and not args.year_end else None),
                    document_type=args.document_type,
                    language=args.language,
                )
                print(
                    f"[{report.status.upper()}] {report.source} "
                    f"(doc={report.document_id}, version={report.version}, "
                    f"chunks={report.chunk_count}, parser={report.parser_name or '—'})"
                )
                if report.error:
                    print(f"    error: {report.error}")
                if report.status == "failed":
                    failures += 1
                else:
                    await conn.commit()
        return 1 if failures else 0
    finally:
        if engine is not None:
            await engine.dispose()


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
