import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

# Importing app modules initializes pydantic-settings; ensure the test
# database URL and test environment are set before that happens.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_test",
)

# Safety rail: the test suite drops/creates the schema and truncates every
# table. It must never run against a managed/shared database. This guard also
# catches an accidental TEST_DATABASE_URL that points at, say, Supabase.
_test_host = (urlparse(TEST_DATABASE_URL).hostname or "").lower()
if any(marker in _test_host for marker in ("supabase", "pooler")):
    raise RuntimeError(
        "Refusing to run the destructive test suite against a hosted database "
        f"({_test_host!r}). Set TEST_DATABASE_URL to a dedicated local database."
    )

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"
# Phase 6 config validation refuses an empty/short JWT secret outside
# development; the hermetic suite sets a deterministic secret for tests.
os.environ.setdefault("JWT_SECRET", "test-secret-for-digital-twin-tests-0123456789abcdef")
# RAG is forced off for the Phase 1-4 hermetic suite so the agent never
# attempts real BGE-M3 retrieval (which downloads weights). Phase 5 RAG tests
# opt back in by injecting RAGService(..., enabled=True) with stub adapters.
os.environ.setdefault("RAG_ENABLED", "false")

from app.core.config import get_settings  # noqa: E402
from app.core.database import (  # noqa: E402
    dispose_engine,
    get_engine,
    get_session_factory,
    init_engine,
)
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


def _maintenance_asyncpg_url(url: str) -> str:
    """Return the same URL but pointing at the 'postgres' maintenance database."""
    return url.replace("/digital_twin_test", "/postgres", 1).replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )


async def _ensure_test_database_exists() -> None:
    maintenance_url = _maintenance_asyncpg_url(TEST_DATABASE_URL)
    conn = await asyncpg.connect(maintenance_url)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'digital_twin_test'"
        )
        if not exists:
            await conn.execute("CREATE DATABASE digital_twin_test")
    finally:
        await conn.close()


async def _truncate_all() -> None:
    tables = (
        "refresh_tokens, users, telemetry_records, vehicle_health_snapshots, "
        "agent_diagnoses, vehicles"
    )
    if supports_pgvector():
        tables = f"rag_chunks, rag_document_versions, rag_documents, {tables}"
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def supports_pgvector() -> bool:
    """Best-effort, cached probe: can the test database serve ``vector``?

    Used at *collection* time by Phase 5 integration tests so they skip cleanly
    when the local test server cannot install the pgvector extension.
    """
    if getattr(supports_pgvector, "_cached", None) is not None:
        return supports_pgvector._cached  # type: ignore[attr-defined]

    async def _probe() -> bool:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                res = await conn.execute(
                    text("select 1 from pg_extension where extname = 'vector'")
                )
            return bool(res.scalar())
        except Exception:
            return False
        finally:
            await engine.dispose()

    try:
        import asyncio

        result = asyncio.run(_probe())
    except Exception:
        result = False
    supports_pgvector._cached = result  # type: ignore[attr-defined]
    return result


@pytest_asyncio.fixture(scope="session")
async def test_app_engine() -> AsyncIterator[None]:
    """Point the app engine at the test database and build the schema.

    Provision pgvector on the *test* database when the local server supports it
    (Phase 5 integration tests skip when it does not); otherwise build only the
    Phase 1-4 schema so the rest of the suite still runs. Never target a hosted
    database.
    """
    await _ensure_test_database_exists()

    vector_ok = await asyncio.to_thread(supports_pgvector)
    non_rag_tables = [t for t in Base.metadata.sorted_tables if not t.name.startswith("rag_")]

    init_engine(get_settings())
    engine = get_engine()
    async with engine.begin() as conn:
        if vector_ok:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    async with engine.begin() as conn:
        if vector_ok:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        else:
            await conn.run_sync(Base.metadata.drop_all, tables=non_rag_tables)
            await conn.run_sync(Base.metadata.create_all, tables=non_rag_tables)

    yield

    async with engine.begin() as conn:
        if vector_ok:
            await conn.run_sync(Base.metadata.drop_all)
        else:
            await conn.run_sync(Base.metadata.drop_all, tables=non_rag_tables)
    await dispose_engine()


@pytest_asyncio.fixture
async def clean_db(test_app_engine) -> AsyncIterator[None]:
    """Truncate all tables before and after every test to avoid pollution."""
    await _truncate_all()
    yield
    await _truncate_all()


@pytest_asyncio.fixture
async def session_factory(test_app_engine) -> async_sessionmaker:
    return get_session_factory()


@pytest_asyncio.fixture
async def client(clean_db) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def _register_and_login(
    client: httpx.AsyncClient,
    *,
    email: str,
    password: str = "Sup3rSecret!",
    full_name: str | None = None,
) -> tuple[dict, str, str]:
    """Register a fresh user over HTTP and return (user_dict, access, refresh)."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    user = response.json()
    token_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert token_resp.status_code == 200, token_resp.text
    body = token_resp.json()
    return user, body["access_token"], body["refresh_token"]


@pytest_asyncio.fixture
async def auth_user(client) -> dict:
    """An ordinary 'user'-role account, registered through the public API."""
    user, _, _ = await _register_and_login(
        client,
        email=f"user.{uuid4().hex[:8]}@example.com",
        full_name="Alice Test",
    )
    assert user["role"] == "user"
    return user


@pytest_asyncio.fixture
async def auth_client(client, auth_user) -> httpx.AsyncClient:
    """HTTP client authenticated as the ordinary auth_user."""
    _, access, _ = await _login_for(auth_user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_auth_headers(access),
    ) as c:
        yield c


async def _login_for(user_dict: dict) -> tuple[dict, str, str]:
    """Login helper that re-derives a token pair from a user dict."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/auth/login",
            json={"email": user_dict["email"], "password": "Sup3rSecret!"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        return body, body["access_token"], body["refresh_token"]


async def _create_user_via_db(full_name: str, *, role: str = "user") -> dict:
    """Create a user directly (e.g. an admin) and log in via the API."""
    from app.core.database import get_session_factory  # noqa: PLC0415
    from app.core.security import hash_password  # noqa: PLC0415
    from app.models.user import User  # noqa: PLC0415

    email = f"{role}.{uuid4().hex[:8]}@example.com"
    password = "Sup3rSecret!"
    async with get_session_factory()() as session:
        user = User(
            email=email,
            password_hash=hash_password(password),
            role=role,
            full_name=full_name,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_dict = {
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
        }
    return user_dict


@pytest_asyncio.fixture
async def admin_user(client) -> dict:
    return await _create_user_via_db("Admin Alice", role="admin")


@pytest_asyncio.fixture
async def admin_client(client, admin_user) -> httpx.AsyncClient:
    """HTTP client authenticated as an admin-role user."""
    _, access, _ = await _login_for(admin_user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_auth_headers(access),
    ) as c:
        yield c


@pytest_asyncio.fixture
async def other_user(client) -> dict:
    """A second ordinary user who does not own any fixtures."""
    user, _, _ = await _register_and_login(
        client,
        email=f"other.{uuid4().hex[:8]}@example.com",
        full_name="Other User",
    )
    return user


@pytest_asyncio.fixture
async def other_user_client(client, other_user) -> httpx.AsyncClient:
    _, access, _ = await _login_for(other_user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_auth_headers(access),
    ) as c:
        yield c


@pytest_asyncio.fixture
async def sample_vehicle(auth_client) -> dict:
    """A vehicle owned by auth_user, created through the authenticated API."""
    response = await auth_client.post(
        "/api/v1/vehicles",
        json={
            "vin": unique_vin(),
            "make": "Toyota",
            "model": "Camry",
            "year": 2024,
            "engine_type": "2.5L Petrol",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def unique_vin(prefix: str = "TESTVIN") -> str:
    return f"{prefix}{uuid4().hex[:10].upper()}"
