import os
from collections.abc import AsyncIterator
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
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"

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
    async with get_engine().begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE telemetry_records, vehicles RESTART IDENTITY CASCADE")
        )


@pytest_asyncio.fixture(scope="session", autouse=True)
async def test_app_engine() -> AsyncIterator[None]:
    """Point the app engine at the test database and build the schema."""
    await _ensure_test_database_exists()

    init_engine(get_settings())
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await dispose_engine()


@pytest_asyncio.fixture(autouse=True)
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


@pytest_asyncio.fixture
async def sample_vehicle(client) -> dict:
    response = await client.post(
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
