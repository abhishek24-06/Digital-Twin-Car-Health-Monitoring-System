"""Phase B: deployment verification endpoint.

``GET /api/v1/health/deployment`` is admin-only, read-only, and must report the
build identity, the feature routes the process actually exposes, and any schema
drift without ever applying a migration or leaking the database URL.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text

from app.api.routes import health as health_route
from app.core.config import get_settings
from app.core.database import get_session_factory


def _patched_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    settings = get_settings().model_copy(update=overrides)
    monkeypatch.setattr(health_route, "get_settings", lambda: settings)


async def test_deployment_status_requires_authentication(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/health/deployment")
    assert response.status_code == 401


async def test_deployment_status_requires_admin(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/health/deployment")
    assert response.status_code == 403


async def test_deployment_status_reports_features_and_unconfigured_revision(
    admin_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patched_settings(monkeypatch, build_id="test-build-1", expected_schema_revision=None)

    response = await admin_client.get("/api/v1/health/deployment")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["service"] == "digital-twin-api"
    assert body["build_id"] == "test-build-1"
    assert body["database_reachable"] is True
    # The test database is built from metadata, not Alembic, so there is no
    # revision table to read.
    assert body["database_schema_revision"] is None
    assert body["expected_schema_revision"] is None
    assert body["migration_in_sync"] is None

    assert body["features"]["alerts_api"] is True
    assert body["features"]["live_health_api"] is True
    assert body["features"]["historical_analytics_api"] is True

    joined = " ".join(response.json()["diagnostics"])
    assert "not migrated" in joined
    assert "EXPECTED_SCHEMA_REVISION is not configured" in joined

    # Never expose the database URL anywhere in the payload.
    assert "postgresql" not in response.text.lower()


_DEPLOYMENT_KEYS = {
    "service",
    "app_version",
    "build_id",
    "environment",
    "database_reachable",
    "expected_schema_revision",
    "database_schema_revision",
    "migration_in_sync",
    "features",
    "diagnostics",
}


async def test_deployment_status_exposes_no_secrets_or_extra_env(
    admin_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The payload is an exact, curated allow-list - never a dump of settings."""
    _patched_settings(monkeypatch, build_id="build-x", expected_schema_revision="rev-x")

    response = await admin_client.get("/api/v1/health/deployment")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == _DEPLOYMENT_KEYS
    assert set(body["features"]) == {
        "alerts_api",
        "live_health_api",
        "historical_analytics_api",
    }

    lowered = response.text.lower()
    for needle in (
        "password",
        "secret",
        "postgres",
        "supabase",
        "jwt",
        "token",
        "://",
        "database_url",
        "127.0.0.1",
    ):
        assert needle not in lowered, f"deployment status leaked {needle!r}"


async def test_deployment_status_detects_schema_drift(
    admin_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        await session.execute(text("DELETE FROM alembic_version"))
        await session.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": "rev-a"},
        )
        await session.commit()

    try:
        _patched_settings(monkeypatch, build_id="test-build-2", expected_schema_revision="rev-a")
        matched = await admin_client.get("/api/v1/health/deployment")
        assert matched.status_code == 200, matched.text
        body = matched.json()
        assert body["database_schema_revision"] == "rev-a"
        assert body["migration_in_sync"] is True
        assert "matches the revision expected" in " ".join(body["diagnostics"])

        _patched_settings(monkeypatch, build_id="test-build-3", expected_schema_revision="rev-b")
        drifted = await admin_client.get("/api/v1/health/deployment")
        assert drifted.status_code == 200, drifted.text
        body = drifted.json()
        assert body["database_schema_revision"] == "rev-a"
        assert body["expected_schema_revision"] == "rev-b"
        assert body["migration_in_sync"] is False
        assert "Schema drift" in " ".join(body["diagnostics"])
    finally:
        async with get_session_factory()() as session:
            await session.execute(text("DROP TABLE IF EXISTS alembic_version"))
            await session.commit()
