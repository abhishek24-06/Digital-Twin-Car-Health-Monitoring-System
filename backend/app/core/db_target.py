"""Database target classification and destructive-op guardrails (Phase 13).

Every ``DATABASE_URL`` in this project is one of three targets:

* ``supabase`` - the hosted Supabase PostgreSQL used by the normal runtime
  pipeline (FastAPI, subscriber, migrations, and indirectly the frontend).
* ``local`` - an explicitly local PostgreSQL (``localhost``/``127.0.0.1``)
  used for isolated development experiments that must not join the runtime
  pipeline.
* ``remote`` - any other reachable host.

Destructive development tooling (schema resets, bulk deletes, ...) MUST refuse
to run against anything that is not ``local``. This module is the single
source of truth for that classification so scripts cannot drift or rely on a
developer remembering which database is active. Credentials are never handled
here beyond URL parsing and are never printed.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_SUPABASE_HOST_HINT = "supabase.co"

Target = str  # one of: "supabase" | "local" | "remote"


def classify_database_url(url: str) -> Target:
    """Classify a ``DATABASE_URL`` as ``supabase``, ``local`` or ``remote``."""
    host = (urlsplit(url).hostname or "").lower()
    if host in _LOCAL_HOSTS:
        return "local"
    if _SUPABASE_HOST_HINT in host:
        return "supabase"
    return "remote"


def database_target(url: str) -> Target:
    """Alias for :func:`classify_database_url` with an explicit name."""
    return classify_database_url(url)


def describe_database_url(url: str) -> str:
    """Return ``host[:port]/dbname`` with all credentials redacted."""
    parts = urlsplit(url)
    host = parts.hostname or "?"
    port = f":{parts.port}" if parts.port else ""
    name = (parts.path or "").rsplit("/", 1)[-1] or "?"
    return f"{host}{port}/{name}"


def require_local_database(url: str, action: str) -> None:
    """Raise unless the given ``DATABASE_URL`` targets an explicitly local DB.

    Passwords and usernames are never echoed; only the redacted target is
    shown when the guard trips.
    """
    target = classify_database_url(url)
    if target != "local":
        raise RuntimeError(
            f"Refusing to {action}: DATABASE_URL targets {target} "
            f"({describe_database_url(url)}). Only an explicitly local database "
            "(localhost/127.0.0.1) may be used for destructive development operations."
        )
