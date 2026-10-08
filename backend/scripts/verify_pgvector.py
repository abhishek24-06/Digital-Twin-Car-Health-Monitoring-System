"""Independent pgvector schema probe (Phase 4, devtooling).

Connects to the configured ``DATABASE_URL`` with asyncpg directly (no app
engine, no running services) and asserts the pieces migration
4f9d3c2b1a8e (phase5 RAG tables) actually landed and are serviceable:

* the ``vector`` extension is installed,
* the ``ix_rag_chunk_embedding`` HNSW index exists on ``rag_chunks``,
* the ``vector`` type and the ``<#>`` (inner product) operator execute.

Used by the CI migration verification step after ``alembic upgrade head``;
also runnable locally, e.g. ``make db-verify``. Exits non-zero on failure.
Credentials are never printed.
"""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import parse_qs, urlsplit

_EXPECTED_INNER_PRODUCT = 17.0  # [1,2,3] <#> [4,5,1]


async def _failures() -> list[str]:
    try:
        import asyncpg
    except ImportError:
        return ["asyncpg is not installed"]

    from app.core.config import get_settings

    parts = urlsplit(get_settings().sync_database_url)
    # asyncpg only accepts `ssl` as an explicit connect keyword, not as a
    # runtime parameter; normalise exactly like scripts/check_db.py.
    query = parse_qs(parts.query)
    ssl_arg = (query.get("ssl") or query.get("sslmode") or [None])[0]
    dsn = parts._replace(query="").geturl()

    failures: list[str] = []
    try:
        conn = await asyncpg.connect(dsn, timeout=10, ssl=ssl_arg)
    except Exception as exc:  # noqa: BLE001 - report any failure for diagnosis
        return [f"connection failed: {type(exc).__name__}: {exc}"]

    try:
        ext = await conn.fetchval("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        if not ext:
            failures.append("vector extension is not installed (pgvector required)")

        indexdef = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'rag_chunks' AND indexname = 'ix_rag_chunk_embedding'"
        )
        if not indexdef:
            failures.append("HNSW index ix_rag_chunk_embedding is missing on rag_chunks")
        elif "USING hnsw" not in indexdef or "vector_cosine_ops" not in indexdef:
            failures.append(
                f"ix_rag_chunk_embedding is not the expected HNSW vector index: {indexdef}"
            )

        result = await conn.fetchval("SELECT '[1,2,3]'::vector(3) <#> '[4,5,1]'::vector(3)")
        if result != _EXPECTED_INNER_PRODUCT:
            failures.append(
                f"vector operator check failed (got {result!r}, expected {_EXPECTED_INNER_PRODUCT})"
            )
    finally:
        await conn.close()

    return failures


def main() -> int:
    failures = asyncio.run(_failures())
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(
        "pgvector verification passed: extension, HNSW index and vector operators are serviceable"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
