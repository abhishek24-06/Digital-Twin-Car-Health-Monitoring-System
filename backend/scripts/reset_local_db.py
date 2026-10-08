"""Guarded local-only PostgreSQL schema reset for development (Phase 13).

This is the tooling that *must never* run against Supabase. It reads the
configured ``DATABASE_URL`` (from ``backend/.env``), classifies the target and
exits non-zero unless **all** of the following hold:

* the target is explicitly local (``localhost``/``127.0.0.1``/``::1``),
* ``--yes`` was passed (no interactive foot-gun, CI-friendly),
* ``--include`` does not widen the operation past a trusted reset.

The reset itself is transactional: ``DROP SCHEMA public CASCADE`` followed by
``CREATE SCHEMA public``, so it never leaves the database mid-way. Optional
``--with-pgvector`` also reinstalls the ``vector`` extension.

Usage:
    python -m scripts.reset_local_db --yes
    python -m scripts.reset_local_db --yes --with-pgvector

Example of a refused (safe) invocation against Supabase:

    $ python -m scripts.reset_local_db --yes
    Refusing to reset schema: DATABASE_URL targets supabase (db.xxx.supabase.co:5432/postgres).
"""

from __future__ import annotations

import argparse
import sys

import sqlalchemy as sa

from app.core.config import get_settings
from app.core.db_target import require_local_database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset the schema of an explicitly local database (refuses Supabase/remote)."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        required=True,
        help="Confirm the destructive reset (mandatory).",
    )
    parser.add_argument(
        "--with-pgvector",
        action="store_true",
        help="Also create the pgvector extension after recreating the schema.",
    )
    args = parser.parse_args()

    url = get_settings().sync_database_url
    try:
        require_local_database(url, "reset the database schema")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f"Resetting LOCAL database {url.split('@')[-1].split('?')[0]} "
        "(DROP SCHEMA public CASCADE; CREATE SCHEMA public; ...)"
    )
    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(sa.text("CREATE SCHEMA public"))
            if args.with_pgvector:
                connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        engine.dispose()
    print("Local schema reset complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
