from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.alert_repository import AlertRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.alert_service import AlertService
from tests.conftest import unique_vin

ALERT_BASE = "/api/v1/vehicles/{vehicle_id}/alerts"


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession], clean_db) -> AsyncSession:
    async with session_factory() as s:
        yield s


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


async def _seed_alert(session: AsyncSession, vehicle_id: str, findings: list[dict] | None = None):
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


async def test_list_alerts_empty(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await auth_client.get(ALERT_BASE.format(vehicle_id=sample_vehicle["id"]))
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}


async def test_list_alerts_returns_seeded_alert(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _seed_alert(session, vehicle_id)

    response = await auth_client.get(ALERT_BASE.format(vehicle_id=vehicle_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["vehicle_id"] == vehicle_id
    assert item["rule_id"] == "COOLANT_TEMP_HIGH"
    assert item["severity"] == "critical"
    assert item["status"] == "open"
    assert item["occurrence_count"] == 1
    assert item["title"] == "Coolant temperature high"
    assert "evidence" not in item


async def test_list_alerts_filters_status_and_severity(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _seed_alert(
        session,
        vehicle_id,
        [_finding(), _finding("warning", "BATTERY_VOLTAGE_LOW")],
    )

    criticals = await auth_client.get(
        ALERT_BASE.format(vehicle_id=vehicle_id), params={"severity": "critical"}
    )
    assert criticals.status_code == 200
    assert criticals.json()["total"] == 1
    assert criticals.json()["items"][0]["rule_id"] == "COOLANT_TEMP_HIGH"

    opened = await auth_client.get(
        ALERT_BASE.format(vehicle_id=vehicle_id), params={"status": "open"}
    )
    assert opened.json()["total"] == 2

    resolved = await auth_client.get(
        ALERT_BASE.format(vehicle_id=vehicle_id), params={"status": "resolved"}
    )
    assert resolved.json()["total"] == 0


async def test_get_alert_detail_includes_history(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    vehicle_id = sample_vehicle["id"]
    [alert] = await _seed_alert(session, vehicle_id)

    response = await auth_client.get(f"{ALERT_BASE.format(vehicle_id=vehicle_id)}/{alert.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(alert.id)
    assert body["evidence"]["observed_value"] == 120.0
    assert [e["event_type"] for e in body["events"]] == ["created"]
    assert body["events"][0]["actor_user_id"] is None


async def test_acknowledge_then_resolve_flow(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    vehicle_id = sample_vehicle["id"]
    [alert] = await _seed_alert(session, vehicle_id)
    base = f"{ALERT_BASE.format(vehicle_id=vehicle_id)}/{alert.id}"

    ack = await auth_client.post(f"{base}/acknowledge", json={"note": "on it"})
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledge_note"] == "on it"
    assert ack.json()["acknowledged_by"] is not None

    resolved = await auth_client.post(f"{base}/resolve", json={"note": "fixed"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_note"] == "fixed"
    assert [e["event_type"] for e in resolved.json()["events"]] == [
        "created",
        "acknowledged",
        "resolved",
    ]


async def test_resolve_accepts_an_empty_body(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    vehicle_id = sample_vehicle["id"]
    [alert] = await _seed_alert(session, vehicle_id)

    response = await auth_client.post(
        f"{ALERT_BASE.format(vehicle_id=vehicle_id)}/{alert.id}/resolve"
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"


async def test_acknowledging_a_resolved_alert_is_a_conflict(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    vehicle_id = sample_vehicle["id"]
    [alert] = await _seed_alert(session, vehicle_id)
    base = f"{ALERT_BASE.format(vehicle_id=vehicle_id)}/{alert.id}"

    assert (await auth_client.post(f"{base}/resolve")).status_code == 200
    conflict = await auth_client.post(f"{base}/acknowledge")
    assert conflict.status_code == 409, conflict.text


async def test_unknown_alert_is_404(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await auth_client.get(
        f"{ALERT_BASE.format(vehicle_id=sample_vehicle['id'])}/{uuid4()}"
    )
    assert response.status_code == 404


async def test_alert_of_another_vehicle_is_404(
    auth_client: httpx.AsyncClient, sample_vehicle: dict, session: AsyncSession
) -> None:
    [alert] = await _seed_alert(session, sample_vehicle["id"])
    other = await auth_client.post(
        "/api/v1/vehicles",
        json={
            "vin": unique_vin(),
            "make": "Honda",
            "model": "Civic",
            "year": 2023,
        },
    )
    assert other.status_code == 201, other.text
    response = await auth_client.get(
        f"{ALERT_BASE.format(vehicle_id=other.json()['id'])}/{alert.id}"
    )
    assert response.status_code == 404


async def test_other_user_cannot_see_alerts(
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
    session: AsyncSession,
) -> None:
    [alert] = await _seed_alert(session, sample_vehicle["id"])
    vehicle_id = sample_vehicle["id"]

    listing = await other_user_client.get(ALERT_BASE.format(vehicle_id=vehicle_id))
    assert listing.status_code == 404

    detail = await other_user_client.get(f"{ALERT_BASE.format(vehicle_id=vehicle_id)}/{alert.id}")
    assert detail.status_code == 404


async def test_unauthenticated_is_401(client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await client.get(ALERT_BASE.format(vehicle_id=sample_vehicle["id"]))
    assert response.status_code == 401
