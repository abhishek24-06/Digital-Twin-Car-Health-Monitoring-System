"""Launch an isolated backend for the Playwright acceptance suite (Phase D).

Fail-closed, disposable, and deterministic:

* Requires ``E2E_DATABASE_URL`` pointing at a **loopback** database named
  ``digital_twin_browser_test``. Anything else aborts the run.
* Creates the schema (non-``rag_`` tables: no pgvector needed) and seeds two
  owners, two vehicles and a window of telemetry.
* Serves the real FastAPI app with **mock** LLM providers and the background
  health monitor disabled, so acceptance is fast and offline.

It never edits ``backend/.env``, never touches the hosted database, and never
talks to the running dev server.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]

E2E_DB_NAME = "digital_twin_browser_test"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
HOSTED_MARKERS = ("supabase", "pooler", "amazonaws", "render.com", "neon.tech")

OWNER_EMAIL = "owner@e2e-digitaltwin.com"
OTHER_EMAIL = "intruder@e2e-digitaltwin.com"
DEMO_PASSWORD = "E2ePassword123"

# A throwaway, non-secret value used only for this disposable backend.
E2E_JWT_SECRET = "e2e-only-not-a-production-secret-0123456789abcdef"


def _require_isolated_database_url() -> str:
    url = os.environ.get("E2E_DATABASE_URL")
    if not url:
        raise SystemExit(
            "E2E_DATABASE_URL is not set. Point it at a local disposable database, e.g.\n"
            f"  postgresql+asyncpg://postgres:root@127.0.0.1:5432/{E2E_DB_NAME}"
        )

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    db_name = (parsed.path or "").lstrip("/")
    if any(marker in host for marker in HOSTED_MARKERS) or host not in LOCAL_HOSTS:
        raise SystemExit(
            f"Refusing to run the browser acceptance backend against host {host!r}: "
            "it must be loopback."
        )
    if db_name != E2E_DB_NAME:
        raise SystemExit(
            f"Refusing database {db_name!r}: the browser acceptance backend demands a "
            f"dedicated disposable database named {E2E_DB_NAME!r}."
        )
    return url


def _configure_environment(url: str) -> None:
    """Force **all** isolation settings before the app is imported.

    These are assigned (not defaulted) so nothing in the ambient environment or
    ``backend/.env`` can redirect the acceptance backend at real data.
    """
    isolated: dict[str, str] = {
        "DATABASE_URL": url,
        "JWT_SECRET": E2E_JWT_SECRET,
        "APP_ENV": "development",
        "CORS_ORIGINS": '["http://127.0.0.1:3010","http://localhost:3010"]',
        "HEALTH_MONITOR_ENABLED": "false",
        "LLM_PRIMARY_PROVIDER": "mock",
        "LLM_FALLBACK_PROVIDER": "mock",
        # Nothing is listening here: the subscriber reports degraded but the app
        # and every vehicle tab still work.
        "MQTT_BROKER_HOST": "127.0.0.1",
        "MQTT_BROKER_PORT": "1884",
        "WORKFLOW_EVENT_PERSISTENCE_ENABLED": "true",
        # Acceptance drives many logins/analyses from one address; the limiter
        # itself is covered by dedicated backend tests.
        "AUTH_RATE_LIMIT_MAX_REQUESTS": "500",
        "ANALYSIS_RATE_LIMIT_MAX_REQUESTS": "200",
    }
    os.environ.update(isolated)


async def _ensure_database_exists(url: str) -> None:
    import asyncpg

    parsed = urlparse(url)
    conn = await asyncpg.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", E2E_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{E2E_DB_NAME}"')
    finally:
        await conn.close()


async def _seed(url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.security import hash_password
    from app.models import Base
    from app.models.telemetry import TelemetryRecord
    from app.models.user import ROLE_USER, User
    from app.models.vehicle import Vehicle

    engine = create_async_engine(url, poolclass=NullPool)
    tables = [t for t in Base.metadata.sorted_tables if not t.name.startswith("rag_")]

    await _ensure_database_exists(url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
        # Deterministic reset: this database is disposable by contract, so a
        # fresh seed on every launch keeps acceptance reproducible.
        await conn.execute(
            text("TRUNCATE TABLE telemetry_records, vehicles, users RESTART IDENTITY CASCADE")
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    async with factory() as session:
        owner = User(
            email=OWNER_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            role=ROLE_USER,
            full_name="E2E Owner",
            is_active=True,
        )
        intruder = User(
            email=OTHER_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            role=ROLE_USER,
            full_name="E2E Intruder",
            is_active=True,
        )
        session.add_all([owner, intruder])
        await session.flush()

        vehicle_a = Vehicle(
            vin="E2EVIN0000000001",
            make="Volvo",
            model="XC60",
            year=2024,
            engine_type="Hybrid",
            owner_user_id=owner.id,
            source_type="simulator",
            status="active",
        )
        vehicle_b = Vehicle(
            vin="E2EVIN0000000002",
            make="Saab",
            model="9-3",
            year=2005,
            owner_user_id=intruder.id,
            source_type="simulator",
            status="active",
        )
        session.add_all([vehicle_a, vehicle_b])
        await session.flush()

        run_id = uuid4()
        for i in range(90):
            session.add(
                TelemetryRecord(
                    vehicle_id=vehicle_a.id,
                    timestamp=now - timedelta(seconds=90 - i),
                    rpm=900.0 + (i % 10) * 120.0,
                    speed=40.0 + (i % 7) * 4.0,
                    engine_load=35.0 + (i % 5) * 3.0,
                    coolant_temperature=88.0 + (i % 4),
                    oil_temperature=95.0 + (i % 3),
                    battery_voltage=13.8 - (i % 5) * 0.02,
                    fuel_level=70.0 - i * 0.1,
                    intake_air_temperature=28.0 + (i % 3),
                    throttle_position=15.0 + (i % 6) * 2.0,
                    engine_runtime=float(3600 + i),
                    odometer=45231.7 + i * 0.02,
                    source_event_id=f"e2e-{run_id.hex[:8]}-{i}",
                    simulation_run_id=run_id,
                    raw_payload={"source": "e2e-seed"},
                )
            )
        for i in range(6):
            session.add(
                TelemetryRecord(
                    vehicle_id=vehicle_b.id,
                    timestamp=now - timedelta(seconds=6 - i),
                    rpm=800.0,
                    speed=0.0,
                    source_event_id=f"e2e-b-{i}",
                )
            )
        await session.commit()

        # Run the *real* deterministic engine over the seeded telemetry so the
        # Overview and History tabs load a genuine snapshot instead of the
        # documented "no snapshot yet" 404. No snapshots are fabricated by hand.
        from app.repositories.health_snapshot_repository import (
            HealthSnapshotRepository,
        )
        from app.repositories.telemetry_repository import TelemetryRepository
        from app.repositories.vehicle_repository import VehicleRepository
        from app.services.vehicle_health_service import VehicleHealthService

        health_service = VehicleHealthService(
            session=session,
            vehicle_repository=VehicleRepository(session),
            telemetry_repository=TelemetryRepository(session),
            health_repository=HealthSnapshotRepository(session),
        )
        await health_service.analyze_vehicle(vehicle_a.id)

    await engine.dispose()


def main() -> None:
    url = _require_isolated_database_url()
    _configure_environment(url)

    # SQLAlchemy logs every statement at INFO once the app configures the root
    # logger; keep the acceptance backend's output readable.
    import logging

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    if sys.platform == "win32":
        # aiomqtt (the subscriber) needs a selector loop; make it the default so
        # both the seed step and uvicorn agree.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(_seed(url))

    import uvicorn

    host = os.environ.get("E2E_BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("E2E_BACKEND_PORT", "8010"))
    uvicorn.run("app.main:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
