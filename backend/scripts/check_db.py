"""Independent database connectivity probe (Phase 3.5).

Connects to the configured ``DATABASE_URL`` using the asyncpg driver directly
(no app engine, no running services) and reports reachability, the server
version, and whether the transport is TLS-encrypted.

Credentials are never printed. Usage: ``python -m scripts.check_db`` or
``make db-check``.
"""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import parse_qs, urlsplit


async def main() -> int:
    try:
        import asyncpg
    except ImportError:
        print("asyncpg is not installed.", file=sys.stderr)
        return 2

    from app.core.config import get_settings

    settings = get_settings()
    parts = urlsplit(settings.sync_database_url)
    port = parts.port or 5432
    database = (parts.path or "/").lstrip("/") or "?"
    # The URL is authoritative for TLS, but asyncpg accepts the `ssl` value
    # only as an explicit connect keyword (a bare `?ssl=` query is treated as a
    # runtime parameter and rejected). Normalize so one URL works for the
    # SQLAlchemy engine (app/alembic) and this direct probe alike.
    query = parse_qs(parts.query)
    ssl_arg = (query.get("ssl") or query.get("sslmode") or [None])[0]
    dsn = parts._replace(query="").geturl()
    print(f"Target: host={parts.hostname} port={port} database={database} (password hidden)")

    try:
        conn = await asyncpg.connect(dsn, timeout=10, ssl=ssl_arg)
    except Exception as exc:  # noqa: BLE001 - report any failure for diagnosis
        print(f"Connection FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    try:
        version = await conn.fetchval("SELECT version()")
        tls = await conn.fetchval("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
    finally:
        await conn.close()

    print("Connected OK")
    print(f"Server version: {version}")
    print(f"TLS encrypted: {bool(tls)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
