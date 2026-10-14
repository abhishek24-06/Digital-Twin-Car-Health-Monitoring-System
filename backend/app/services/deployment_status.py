"""Deployment verification helpers (Phase B).

Read-only helpers used by ``GET /api/v1/health/deployment`` to compare the
running build with the database's Alembic revision and the feature routes the
process actually exposes. Nothing here applies a migration, mutates data, or
surfaces a connection string.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings


async def read_database_schema_revision(session: AsyncSession) -> str | None:
    """Return the Alembic revision recorded in the database, if any.

    ``None`` when the ``alembic_version`` table is absent (an unmigrated
    database) or unreadable. This never raises: a missing table is an expected
    state, not an error.
    """
    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError:
        # A failed statement leaves the session's transaction unusable; roll it
        # back so the request can complete cleanly.
        await session.rollback()
        return None
    return result.scalar()


def detect_features(app: Any, settings: Settings) -> dict[str, bool]:
    """Which notable API surfaces this process has actually registered.

    Reads the generated OpenAPI schema rather than a hand-maintained flag, so a
    server running older code reports ``alerts_api: false`` even though the
    current source tree contains the Alerts routes. ``settings`` is accepted for
    symmetry with the deployment-status payload but the check is path-based.
    """
    try:
        paths = set(app.openapi().get("paths", {}))
    except Exception:  # pragma: no cover - schema generation is deterministic
        paths = set()
    return {
        "alerts_api": any(path.endswith("/alerts") for path in paths),
        "live_health_api": any(path.endswith("/health/live") for path in paths),
        "historical_analytics_api": any("/historical-analytics" in path for path in paths),
    }


def build_diagnostics(
    *,
    database_reachable: bool,
    actual: str | None,
    expected: str | None,
) -> list[str]:
    """Human-readable, secret-free explanation of the verification result."""
    if not database_reachable:
        return ["Database is not reachable; the schema revision could not be read."]

    notes: list[str] = []
    if actual is None:
        notes.append(
            "No Alembic revision found in the database; it is not migrated to this build's schema."
        )
    if expected is None:
        notes.append(
            "EXPECTED_SCHEMA_REVISION is not configured, so this build cannot "
            "assert a target schema revision."
        )
    elif actual is not None and actual != expected:
        notes.append(
            f"Schema drift: the database is at revision {actual} but this build "
            f"expects {expected}. Apply the reviewed migrations and restart the "
            "backend."
        )
    elif actual == expected:
        notes.append("Database schema revision matches the revision expected by this build.")
    return notes
