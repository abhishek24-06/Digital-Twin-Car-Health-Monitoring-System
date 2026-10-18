"""API tests for the read-only fleet overview endpoint.

Covers auth, the honest classification of telemetry freshness, the
timestamp/limit context attached to stored assessments, active-alert counts,
ownership isolation, and the KPI totals. The simulator manager and the
subscriber supervisor are overridden with in-process fakes so no OS subprocess
is ever spawned.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.main import app
from app.models.alert import Alert
from app.models.health_snapshot import HealthSnapshot
from app.models.telemetry import TelemetryRecord
from app.repositories.alert_repository import AlertRepository
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.services.simulation_manager import SimulationManager, get_simulation_manager
from app.services.subscriber_manager import SubscriberHealth, get_subscriber_supervisor
from tests.services.test_simulation_manager import FakeProcessRunner

FLEET_URL = "/api/v1/fleet/overview"

EXPECTED_ROW_KEYS = {
    "vehicle_id",
    "vin",
    "make",
    "model",
    "year",
    "engine_type",
    "status",
    "simulation_state",
    "simulation_scenario",
    "simulation_started_at",
    "simulation_error",
    "last_telemetry_at",
    "telemetry_freshness",
    "assessment",
    "assessment_freshness",
    "open_alerts",
    "critical_open_alerts",
    "warning_open_alerts",
    "requires_attention",
}


class FakeSubscriber:
    def __init__(self, running: bool = True) -> None:
        self._running = running

    async def health(self) -> SubscriberHealth:
        return SubscriberHealth(running=self._running)


@pytest_asyncio.fixture(autouse=True)
async def simulation_manager(tmp_path):
    manager = SimulationManager(
        get_settings(),
        FakeProcessRunner(),
        runtime_dir=tmp_path / "fleet-sims",
        grace_seconds=0.02,
        stop_timeout_seconds=0.05,
    )
    app.dependency_overrides[get_simulation_manager] = lambda: manager
    app.dependency_overrides[get_subscriber_supervisor] = lambda: FakeSubscriber(running=True)
    yield manager
    app.dependency_overrides.pop(get_subscriber_supervisor, None)
    await manager.shutdown()
    app.dependency_overrides.pop(get_simulation_manager, None)


@pytest_asyncio.fixture
async def session(clean_db, session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with session_factory() as s:
        yield s


def _row(body: dict, vehicle_id: str) -> dict:
    return next(item for item in body["vehicles"] if item["vehicle_id"] == vehicle_id)


async def _add_telemetry(session: AsyncSession, vehicle_id: str, ts: datetime) -> None:
    await TelemetryRepository(session).create(
        TelemetryRecord(vehicle_id=UUID(vehicle_id), timestamp=ts, rpm=900.0, speed=0.0)
    )
    await session.commit()


async def _add_snapshot(
    session: AsyncSession,
    vehicle_id: str,
    *,
    generated_at: datetime,
    health_status: str = "healthy",
    score: float | None = 96.0,
    provisional: bool = False,
    provisional_rating: str | None = None,
    data_sufficiency: str = "sufficient_data",
    analysis_scope: str = "current_session",
) -> HealthSnapshot:
    snapshot = HealthSnapshot(
        vehicle_id=UUID(vehicle_id),
        generated_at=generated_at,
        window_start=generated_at - timedelta(minutes=1),
        window_end=generated_at,
        sample_count=120,
        health_score=score,
        health_status=health_status,
        confidence=0.91,
        context_schema_version="1.0",
        context_json={
            "vehicle_id": vehicle_id,
            "health_status": health_status,
            "provisional": provisional,
            "provisional_rating": provisional_rating,
            "data_sufficiency": data_sufficiency,
            "analysis_scope": analysis_scope,
        },
    )
    await HealthSnapshotRepository(session).create(snapshot)
    await session.commit()
    return snapshot


async def _add_alert(
    session: AsyncSession,
    vehicle_id: str,
    *,
    severity: str = "warning",
    status: str = "open",
    dedup_suffix: str = "A",
) -> Alert:
    now = datetime.now(UTC)
    alert = Alert(
        vehicle_id=UUID(vehicle_id),
        dedup_key=f"{vehicle_id}:{dedup_suffix}",
        rule_id="COOLANT_TEMP_HIGH",
        severity=severity,
        status=status,
        title="Coolant temperature high",
        message="Coolant temperature exceeded the configured threshold.",
        occurrence_count=1,
        first_seen_at=now,
        last_seen_at=now,
    )
    await AlertRepository(session).create(alert)
    await session.commit()
    return alert


async def test_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get(FLEET_URL)
    assert response.status_code == 401


async def test_empty_fleet_totals_are_zero(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get(FLEET_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vehicles"] == []
    assert body["totals"] == {
        "vehicles": 0,
        "vehicles_with_recent_telemetry": 0,
        "vehicles_requiring_attention": 0,
        "vehicles_with_open_alerts": 0,
        "active_simulations": 0,
        "open_alerts": 0,
        "critical_open_alerts": 0,
    }


async def test_thresholds_are_echoed_from_backend(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get(FLEET_URL)
    body = response.json()
    settings = get_settings()
    assert body["telemetry_stale_after_seconds"] > 0
    assert body["assessment_stale_after_seconds"] >= settings.health_monitor_min_seconds


async def test_vehicle_without_data_is_no_data(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.get(FLEET_URL)
    row = _row(response.json(), sample_vehicle["id"])

    assert set(row) == EXPECTED_ROW_KEYS
    assert row["telemetry_freshness"] == "no_data"
    assert row["last_telemetry_at"] is None
    assert row["assessment"] is None
    assert row["assessment_freshness"] == "none"
    assert row["requires_attention"] is False
    assert row["open_alerts"] == 0


async def test_recent_telemetry_is_recent(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    await _add_telemetry(session, sample_vehicle["id"], datetime.now(UTC))

    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    assert row["telemetry_freshness"] == "recent"
    assert row["last_telemetry_at"] is not None
    assert body["totals"]["vehicles_with_recent_telemetry"] == 1


async def test_old_telemetry_is_stale(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    stale_after = (await auth_client.get(FLEET_URL)).json()["telemetry_stale_after_seconds"]
    await _add_telemetry(
        session, sample_vehicle["id"], datetime.now(UTC) - timedelta(seconds=stale_after * 4)
    )

    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    assert row["telemetry_freshness"] == "stale"
    assert body["totals"]["vehicles_with_recent_telemetry"] == 0


async def test_attention_assessment_requires_attention(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    await _add_snapshot(
        session,
        sample_vehicle["id"],
        generated_at=datetime.now(UTC),
        health_status="attention",
        score=58.0,
    )

    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    assert row["assessment"]["health_status"] == "attention"
    assert row["assessment"]["health_score"] == 58.0
    assert row["assessment_freshness"] == "fresh"
    assert row["requires_attention"] is True
    assert body["totals"]["vehicles_requiring_attention"] == 1


async def test_stale_assessment_does_not_require_attention(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    await _add_snapshot(
        session,
        sample_vehicle["id"],
        generated_at=datetime.now(UTC) - timedelta(hours=3),
        health_status="critical",
        score=20.0,
    )

    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    # The score is preserved with its own timestamp, but an aged assessment must
    # not be counted as a present-day problem.
    assert row["assessment"]["health_status"] == "critical"
    assert row["assessment_freshness"] == "stale"
    assert row["requires_attention"] is False
    assert body["totals"]["vehicles_requiring_attention"] == 0


async def test_provisional_limited_data_uses_provisional_rating(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    await _add_snapshot(
        session,
        sample_vehicle["id"],
        generated_at=datetime.now(UTC),
        health_status="limited_data",
        score=None,
        provisional=True,
        provisional_rating="critical",
        data_sufficiency="limited_data",
    )

    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    assert row["assessment"]["health_status"] == "limited_data"
    assert row["assessment"]["provisional"] is True
    assert row["assessment"]["provisional_rating"] == "critical"
    # A provisional critical is still a problem, never neutral.
    assert row["requires_attention"] is True


async def test_latest_snapshot_wins(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    await _add_snapshot(
        session, sample_vehicle["id"], generated_at=now - timedelta(minutes=5), health_status="attention"
    )
    await _add_snapshot(session, sample_vehicle["id"], generated_at=now, health_status="healthy")

    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    assert row["assessment"]["health_status"] == "healthy"
    assert row["requires_attention"] is False


async def test_active_alert_requires_attention_and_counts(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    await _add_alert(session, sample_vehicle["id"], severity="critical", dedup_suffix="A")
    await _add_alert(session, sample_vehicle["id"], severity="warning", dedup_suffix="B")
    await _add_alert(
        session, sample_vehicle["id"], severity="critical", status="resolved", dedup_suffix="C"
    )

    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    assert row["open_alerts"] == 2
    assert row["critical_open_alerts"] == 1
    assert row["warning_open_alerts"] == 1
    assert row["requires_attention"] is True
    assert body["totals"]["vehicles_with_open_alerts"] == 1
    assert body["totals"]["open_alerts"] == 2
    assert body["totals"]["critical_open_alerts"] == 1


async def test_ownership_isolation(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    admin_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    owner_body = (await auth_client.get(FLEET_URL)).json()
    assert [row["vehicle_id"] for row in owner_body["vehicles"]] == [sample_vehicle["id"]]

    other_body = (await other_user_client.get(FLEET_URL)).json()
    assert other_body["vehicles"] == []
    assert other_body["totals"]["vehicles"] == 0

    admin_body = (await admin_client.get(FLEET_URL)).json()
    assert sample_vehicle["id"] in [row["vehicle_id"] for row in admin_body["vehicles"]]


async def test_stopped_simulation_reports_stopped(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    assert row["simulation_state"] == "stopped"
    assert body["totals"]["active_simulations"] == 0


async def test_started_simulation_is_counted(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    started = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/simulation",
        json={"scenario": "normal", "interval_seconds": 5.0},
    )
    assert started.status_code == 201, started.text

    body = (await auth_client.get(FLEET_URL)).json()
    row = _row(body, sample_vehicle["id"])
    assert row["simulation_state"] == "running"
    assert row["simulation_scenario"] == "normal"
    assert body["totals"]["active_simulations"] == 1


async def test_unknown_vehicle_is_not_addressable(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    # A vehicle the caller cannot see must never appear in the overview.
    body = (await auth_client.get(FLEET_URL)).json()
    assert str(uuid4()) not in [row["vehicle_id"] for row in body["vehicles"]]
