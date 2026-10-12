"""Phase 5 — full-system acceptance across the eight vehicle-workspace tabs.

This is the product-level acceptance pass. It drives the *real* FastAPI app over
HTTP (``httpx.ASGITransport``) against a *real* PostgreSQL database (the hermetic
``digital_twin_test`` database), and walks the eight tabs end to end:

    Overview | Live Health | Simulation | Analytics | Telemetry |
    AI Diagnosis | History | Alerts

It adds the cross-tab invariants a per-feature unit suite cannot express:

* a historical (windowed) analysis never fabricates a live alert;
* a stopped / collecting session is never surfaced as current health, even when
  a historical snapshot exists to be mis-reused;
* alerts move open -> acknowledged -> resolved with an append-only audit trail,
  a resolved alert is terminal, and a recurrence mints a *new* alert;
* every vehicle-scoped tab is isolated per owner.

Non-destructive: it uses the sanctioned test database (conftest builds and drops
the schema around the session, and truncates between tests), never a hosted
database; no OS subprocess is spawned (an in-memory process runner drives the
simulation lifecycle) and no LLM is called (the deterministic mock provider
backs the agent service).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.config import AgentSettings
from app.agent.service import AgentService
from app.api.routes import vehicle_health as vehicle_health_route
from app.core.config import get_settings
from app.dependencies.database import get_agent_service, get_db
from app.main import app
from app.repositories.alert_repository import AlertRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.alert_service import AlertService
from app.services.simulation_manager import SimulationManager, get_simulation_manager
from app.services.subscriber_manager import SubscriberHealth, get_subscriber_supervisor
from tests.services.test_simulation_manager import FakeProcessRunner

HEALTHY_PAYLOAD = {
    "rpm": 2000.0,
    "speed": 60.0,
    "engine_load": 30.0,
    "coolant_temperature": 90.0,
    "oil_temperature": 90.0,
    "battery_voltage": 13.5,
    "fuel_level": 60.0,
    "intake_air_temperature": 25.0,
    "throttle_position": 20.0,
    "engine_runtime": 1000.0,
    "odometer": 50000.0,
}

#: The vehicle-scoped tabs' HTTP surface, used by the ownership-isolation pass.
VEHICLE_GET_PATHS = (
    "telemetry",
    "health",
    "health/live",
    "health/history",
    "historical-analytics?range=24h",
    "agent/dashboard",
    "agent/diagnoses",
    "alerts",
    "simulation",
)

#: The exact status body the Simulation tab may expose (never the process).
EXPECTED_SIMULATION_STATUS_KEYS = {
    "vehicle_id",
    "status",
    "scenario",
    "interval_seconds",
    "seed",
    "started_at",
    "error",
    "last_telemetry_at",
    "correlation_id",
    "run_id",
}


def _payload_at(seconds_ago: float) -> dict:
    ts = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    return {"timestamp": ts, **HEALTHY_PAYLOAD}


def _finding(severity: str = "critical", rule_id: str = "COOLANT_TEMP_HIGH") -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "category": "temperature",
        "metric": "coolant_temperature",
        "observed_value": 120.0,
        "threshold": 110.0,
        "unit": "degC",
        "message": "Coolant temperature is significantly elevated.",
        "confidence": 0.9,
        "evidence": {"sample_count": 40},
    }


class _FakeSubscriber:
    def __init__(self, running: bool = True) -> None:
        self._running = running

    async def health(self) -> SubscriberHealth:
        return SubscriberHealth(running=self._running)


class _FakeSimulationManager:
    """Stands in for the process-supervising manager on the live-health route."""

    def __init__(self, *, run_id: UUID | None = None, state: str = "stopped") -> None:
        self._run_id = run_id
        self._state = state

    async def get_status(self, vehicle_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(status=self._state, error=None)

    async def active_run_id(self, vehicle_id: UUID) -> UUID | None:
        return self._run_id


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession], clean_db) -> AsyncSession:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture(autouse=True)
async def acceptance_stack(tmp_path):
    """Keep acceptance hermetic: fake process supervision + mock LLM.

    The Simulation tab is backed by a real ``SimulationManager`` driven by the
    in-memory process runner (true lifecycle semantics, no ``simulator.main``
    subprocess); the agent service uses the deterministic mock provider so the
    no-LLM dashboard hook never needs credentials.
    """
    manager = SimulationManager(
        get_settings(),
        FakeProcessRunner(),
        runtime_dir=tmp_path / "acceptance-sims",
        grace_seconds=0.02,
        stop_timeout_seconds=0.05,
    )

    def _agent_override(session: Annotated[AsyncSession, Depends(get_db)]) -> AgentService:
        return AgentService(
            session,
            settings=AgentSettings(
                llm_primary_provider="mock",
                llm_fallback_provider="",
                llm_max_retries=0,
            ),
        )

    app.dependency_overrides[get_simulation_manager] = lambda: manager
    app.dependency_overrides[get_subscriber_supervisor] = lambda: _FakeSubscriber(running=True)
    app.dependency_overrides[get_agent_service] = _agent_override
    yield manager
    app.dependency_overrides.pop(get_agent_service, None)
    app.dependency_overrides.pop(get_subscriber_supervisor, None)
    await manager.shutdown()
    app.dependency_overrides.pop(get_simulation_manager, None)


async def _ingest(auth_client: httpx.AsyncClient, vehicle_id: str, *, count: int = 40) -> None:
    for index in range(count):
        response = await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry",
            json=_payload_at(count - index),
        )
        assert response.status_code == 201, response.text


async def _ingest_run(
    auth_client: httpx.AsyncClient, vehicle_id: str, run_id: UUID, *, count: int = 5
) -> None:
    for index in range(count):
        seconds_ago = (count - index) * 1.0
        body = {
            "timestamp": (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat(),
            "simulation_run_id": str(run_id),
            **HEALTHY_PAYLOAD,
        }
        response = await auth_client.post(f"/api/v1/vehicles/{vehicle_id}/telemetry", json=body)
        assert response.status_code == 201, response.text


async def _seed_alert(
    session: AsyncSession, vehicle_id: str, findings: list[dict] | None = None
) -> list:
    service = AlertService(
        session=session,
        vehicle_repository=VehicleRepository(session),
        alert_repository=AlertRepository(session),
    )
    snapshot = SimpleNamespace(
        id=uuid4(),
        vehicle_id=UUID(vehicle_id),
        generated_at=datetime.now(UTC),
        context_json={"findings": findings or [_finding()], "provisional": False},
    )
    return await service.sync_from_snapshot(snapshot)


def _assert_status_body(body: dict) -> None:
    assert set(body.keys()) == EXPECTED_SIMULATION_STATUS_KEYS
    for secret_key in ("pid", "env", "command", "cmd"):
        assert secret_key not in body


# --- Overview + Telemetry + AI Diagnosis + History + Analytics ---------------


async def test_overview_telemetry_diagnosis_history_analytics(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]

    # Telemetry tab: ingest one bounded healthy window and read it back.
    await _ingest(auth_client, vehicle_id)
    telemetry = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", params={"page_size": 50}
    )
    assert telemetry.status_code == 200, telemetry.text
    assert telemetry.json()["total"] == 40

    # Analytics tab: read-only aggregate over the persisted telemetry.
    analytics = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/historical-analytics", params={"range": "24h"}
    )
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["vehicle_id"] == vehicle_id

    # History/Health tab: a windowed analysis is explicitly *historical*.
    analyze = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )
    assert analyze.status_code == 200, analyze.text
    assert analyze.json()["analysis_scope"] == "historical_window"

    latest = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health")
    assert latest.status_code == 200, latest.text
    assert latest.json()["analysis_scope"] == "historical_window"

    history = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/history")
    assert history.status_code == 200, history.text
    assert history.json()["total"] >= 1

    # AI Diagnosis tab: the dashboard hook is read-only and needs no LLM.
    dashboard = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/agent/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    dashboard_body = dashboard.json()
    assert dashboard_body["health_context"] is not None
    assert dashboard_body["latest_diagnosis"] is None

    diagnoses = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/agent/diagnoses")
    assert diagnoses.status_code == 200, diagnoses.text
    assert diagnoses.json()["total"] == 0

    # Workflow observability (Phase 2) is reachable.
    workflow = await auth_client.get("/api/v1/workflow/status")
    assert workflow.status_code == 200, workflow.text

    # Cross-tab invariant: a historical analysis must never create a live alert.
    alerts = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/alerts")
    assert alerts.status_code == 200, alerts.text
    assert alerts.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}


# --- Tab: Live Health --------------------------------------------------------


async def test_live_health_never_reuses_a_historical_snapshot(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    vehicle_id = sample_vehicle["id"]

    # A historical snapshot exists (History tab) and must not leak into "current".
    await _ingest(auth_client, vehicle_id)
    analyze = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )
    assert analyze.status_code == 200, analyze.text
    generated_at = analyze.json()["generated_at"]

    # Stopped vehicle: explicitly no session, no current assessment.
    monkeypatch.setattr(
        vehicle_health_route,
        "get_simulation_manager",
        lambda: _FakeSimulationManager(run_id=None, state="stopped"),
    )
    stopped = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
    assert stopped.status_code == 200, stopped.text
    stopped_body = stopped.json()
    assert stopped_body["live_state"] == "no_session"
    assert stopped_body["run_id"] is None
    assert stopped_body["assessment"] is None
    assert stopped_body["sample_count"] == 0
    assert stopped_body["last_evaluated_at"] == generated_at

    # Active run, insufficient fresh current-run evidence: still no assessment.
    run_id = uuid4()
    monkeypatch.setattr(
        vehicle_health_route,
        "get_simulation_manager",
        lambda: _FakeSimulationManager(run_id=run_id, state="running"),
    )
    await _ingest_run(auth_client, vehicle_id, run_id, count=5)
    collecting = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/live")
    assert collecting.status_code == 200, collecting.text
    collecting_body = collecting.json()
    assert collecting_body["run_id"] == str(run_id)
    assert collecting_body["live_state"] == "collecting"
    assert collecting_body["assessment"] is None
    assert collecting_body["insufficiency_reasons"]


# --- Tab: Alerts -------------------------------------------------------------


async def test_alerts_tab_full_lifecycle(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
    session: AsyncSession,
) -> None:
    vehicle_id = sample_vehicle["id"]
    base = f"/api/v1/vehicles/{vehicle_id}/alerts"

    seeded = await _seed_alert(session, vehicle_id, [_finding("critical", "COOLANT_TEMP_HIGH")])
    alert_id = str(seeded[0].id)

    listing = await auth_client.get(base)
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["id"] == alert_id
    assert item["severity"] == "critical"
    assert item["status"] == "open"
    assert "evidence" not in item

    # Filters.
    assert (await auth_client.get(base, params={"severity": "critical"})).json()["total"] == 1
    assert (await auth_client.get(base, params={"severity": "warning"})).json()["total"] == 0
    assert (await auth_client.get(base, params={"status": "open"})).json()["total"] == 1

    # Detail: raw evidence + append-only audit history.
    detail = await auth_client.get(f"{base}/{alert_id}")
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["evidence"]["observed_value"] == 120.0
    assert [e["event_type"] for e in detail_body["events"]] == ["created"]
    assert detail_body["events"][0]["actor_user_id"] is None

    # Acknowledge, then resolve; both attributed to the acting user.
    ack = await auth_client.post(f"{base}/{alert_id}/acknowledge", json={"note": "on it"})
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledged_by"] is not None
    assert ack.json()["acknowledge_note"] == "on it"

    resolved = await auth_client.post(f"{base}/{alert_id}/resolve", json={"note": "fixed"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_note"] == "fixed"
    assert [e["event_type"] for e in resolved.json()["events"]] == [
        "created",
        "acknowledged",
        "resolved",
    ]

    # Resolved is terminal: acknowledge is rejected, resolve is idempotent.
    assert (await auth_client.post(f"{base}/{alert_id}/acknowledge")).status_code == 409
    again = await auth_client.post(f"{base}/{alert_id}/resolve")
    assert again.status_code == 200
    assert again.json()["status"] == "resolved"

    # A recurrence after resolution mints a new alert rather than reopening.
    await _seed_alert(session, vehicle_id, [_finding("critical", "COOLANT_TEMP_HIGH")])
    after = await auth_client.get(base)
    assert after.status_code == 200, after.text
    assert after.json()["total"] == 2
    by_id = {row["id"]: row["status"] for row in after.json()["items"]}
    assert by_id[alert_id] == "resolved"
    assert sorted(by_id.values()) == ["open", "resolved"]

    # Ownership: another user cannot see this vehicle's alerts.
    assert (await other_user_client.get(base)).status_code == 404
    assert (await auth_client.get(f"{base}/{uuid4()}")).status_code == 404


# --- Tab: Simulation ---------------------------------------------------------


async def test_simulation_tab_lifecycle(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    base = f"/api/v1/vehicles/{vehicle_id}/simulation"

    started = await auth_client.post(base, json={"scenario": "normal", "seed": 7})
    assert started.status_code == 201, started.text
    start_body = started.json()
    assert set(start_body.keys()) == EXPECTED_SIMULATION_STATUS_KEYS
    for secret_key in ("pid", "env", "command", "cmd"):
        assert secret_key not in start_body
    assert start_body["status"] == "running"
    assert start_body["run_id"] is not None

    status = await auth_client.get(base)
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "running"

    all_sims = await auth_client.get("/api/v1/simulations")
    assert all_sims.status_code == 200, all_sims.text
    assert vehicle_id in {row["vehicle_id"] for row in all_sims.json()["items"]}

    restarted = await auth_client.post(f"{base}/restart", json={"scenario": "normal"})
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["status"] == "running"
    assert restarted.json()["run_id"] != start_body["run_id"]

    stopped = await auth_client.delete(base)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "stopped"


# --- Cross-tab ownership isolation ------------------------------------------


async def test_cross_tab_ownership_isolation(
    client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    vehicle_id = sample_vehicle["id"]

    for path in VEHICLE_GET_PATHS:
        url = f"/api/v1/vehicles/{vehicle_id}/{path}"
        assert (await other_user_client.get(url)).status_code == 404, url
        assert (await client.get(url)).status_code == 401, url

    telemetry_url = f"/api/v1/vehicles/{vehicle_id}/telemetry"
    assert (await other_user_client.post(telemetry_url, json=_payload_at(0))).status_code == 404
    assert (await client.post(telemetry_url, json=_payload_at(0))).status_code == 401

    analyze_url = f"/api/v1/vehicles/{vehicle_id}/health/analyze"
    assert (await other_user_client.post(analyze_url)).status_code == 404
    assert (await client.post(analyze_url)).status_code == 401
