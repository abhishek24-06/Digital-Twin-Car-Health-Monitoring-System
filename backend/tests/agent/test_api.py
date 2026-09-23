from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import pytest_asyncio
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.config import AgentSettings
from app.agent.service import AgentService
from app.dependencies.database import get_agent_service, get_db
from app.main import app

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


@pytest_asyncio.fixture(autouse=True)
async def mock_agent_dependency() -> None:
    """Route the agent service through the deterministic mock provider."""

    def _override(session: Annotated[AsyncSession, Depends(get_db)]) -> AgentService:
        return AgentService(
            session,
            settings=AgentSettings(
                llm_primary_provider="mock",
                llm_fallback_provider="",
                llm_max_retries=0,
            ),
        )

    app.dependency_overrides[get_agent_service] = _override
    yield
    app.dependency_overrides.pop(get_agent_service, None)


def _payload_at(seconds_ago: float) -> dict:
    ts = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    return {"timestamp": ts, **HEALTHY_PAYLOAD}


async def _ingest(client: httpx.AsyncClient, vehicle_id: str, count: int = 40) -> None:
    for index in range(count):
        response = await client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry",
            json=_payload_at(count - index),
        )
        assert response.status_code == 201, response.text


async def _analyze(client: httpx.AsyncClient, vehicle_id: str) -> dict:
    response = await client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_query_without_snapshot_is_deterministic_and_persisted(
    client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    response = await client.post(
        f"/api/v1/vehicles/{vehicle_id}/agent/query", json={"query": "How is my car?"}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trigger_type"] == "USER_QUERY"
    assert payload["severity"] == "info"
    assert payload["confidence"] == 0.0
    assert "No Vehicle Health Context" in payload["diagnosis"]["summary"]
    assert payload["execution"]["provider"] == ""
    assert payload["id"] is not None

    history = await client.get(f"/api/v1/vehicles/{vehicle_id}/agent/diagnoses")
    assert history.status_code == 200
    assert history.json()["total"] == 1


async def test_query_uses_mock_llm_and_grounds_evidence(
    client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(client, vehicle_id)
    context = await _analyze(client, vehicle_id)
    expected_rules = {f["rule_id"] for f in context["findings"]}

    response = await client.post(
        f"/api/v1/vehicles/{vehicle_id}/agent/query",
        json={"query": "Is the engine near overheating?"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trigger_type"] == "USER_QUERY"
    assert payload["user_query"] == "Is the engine near overheating?"
    assert payload["execution"]["provider"] == "mock"
    evidence_rules = {item["rule_id"] for item in payload["diagnosis"]["evidence"]}
    assert expected_rules <= evidence_rules
    assert payload["diagnosis"]["summary"].startswith("Mock analysis")
    assert payload["id"] is not None
    assert payload["generated_at"]


async def test_query_missing_vehicle_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/00000000-0000-0000-0000-000000000099/agent/query",
        json={"query": "hello"},
    )
    assert response.status_code == 404


async def test_query_empty_string_rejected(client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    response = await client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/agent/query", json={"query": "   "}
    )
    assert response.status_code == 422


async def test_critical_event_dedup_within_cooldown(
    client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(client, vehicle_id)
    await _analyze(client, vehicle_id)
    rules = ["COOLANT_TEMP_HIGH", "RPM_OVERSPEED"]

    first = await client.post(
        f"/api/v1/vehicles/{vehicle_id}/agent/events/critical",
        json={"rule_ids": rules},
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["execution"]["deduplicated"] is False

    second = await client.post(
        f"/api/v1/vehicles/{vehicle_id}/agent/events/critical",
        json={"rule_ids": [rules[0]]},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["execution"]["deduplicated"] is True
    assert second_payload["execution"]["rule_ids"] == [rules[0]]

    third = await client.post(
        f"/api/v1/vehicles/{vehicle_id}/agent/events/critical",
        json={"rule_ids": ["BRAND_NEW_RULE"]},
    )
    assert third.status_code == 200
    third_payload = third.json()
    assert third_payload["execution"]["deduplicated"] is False


async def test_dashboard_never_calls_llm(client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(client, vehicle_id)
    context = await _analyze(client, vehicle_id)

    response = await client.get(f"/api/v1/vehicles/{vehicle_id}/agent/dashboard")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["health_context"]["vehicle_id"] == vehicle_id
    assert payload["health_context"]["health_status"] == context["health_status"]
    assert payload["latest_diagnosis"] is None
    assert payload["diagnosis_age_seconds"] is None

    await client.post(f"/api/v1/vehicles/{vehicle_id}/agent/query", json={"query": "Status?"})
    response = await client.get(f"/api/v1/vehicles/{vehicle_id}/agent/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_diagnosis"] is not None
    assert payload["diagnosis_age_seconds"] is not None


async def test_diagnoses_history_pagination(
    client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(client, vehicle_id)
    await _analyze(client, vehicle_id)
    for index in range(3):
        response = await client.post(
            f"/api/v1/vehicles/{vehicle_id}/agent/query",
            json={"query": f"Question {index}"},
        )
        assert response.status_code == 200

    page = await client.get(f"/api/v1/vehicles/{vehicle_id}/agent/diagnoses")
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    items = body["items"]
    assert all(item["trigger_type"] == "USER_QUERY" for item in items)
    assert items[0]["created_at"] >= items[1]["created_at"]

    page_two = await client.get(
        f"/api/v1/vehicles/{vehicle_id}/agent/diagnoses",
        params={"page": 1, "page_size": 2},
    )
    assert page_two.json()["total"] == 3
    assert len(page_two.json()["items"]) == 2


async def test_latest_diagnosis_endpoint(client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(client, vehicle_id)
    await _analyze(client, vehicle_id)
    await client.post(f"/api/v1/vehicles/{vehicle_id}/agent/query", json={"query": "First?"})
    second = await client.post(
        f"/api/v1/vehicles/{vehicle_id}/agent/query", json={"query": "Second?"}
    )
    second_id = second.json()["id"]

    response = await client.get(f"/api/v1/vehicles/{vehicle_id}/agent/diagnoses/latest")
    assert response.status_code == 200
    assert response.json()["id"] == second_id

    fresh = await client.post(
        "/api/v1/vehicles",
        json={
            "vin": "FRESHVIN0001",
            "make": "Honda",
            "model": "Civic",
            "year": 2023,
            "engine_type": "1.5L Turbo",
        },
    )
    missing = await client.get(f"/api/v1/vehicles/{fresh.json()['id']}/agent/diagnoses/latest")
    assert missing.status_code == 404


async def test_high_temperature_query_reports_critical(
    client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    for index in range(40):
        payload = _payload_at(40 - index)
        payload["coolant_temperature"] = 115.0
        response = await client.post(f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload)
        assert response.status_code == 201, response.text
    context = await _analyze(client, vehicle_id)
    assert any(
        f["rule_id"] == "COOLANT_TEMP_HIGH" and f["severity"] == "critical"
        for f in context["findings"]
    )

    response = await client.post(
        f"/api/v1/vehicles/{vehicle_id}/agent/query",
        json={"query": "Engine is running hot. What should I do?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["severity"] == "critical"
    evidence = payload["diagnosis"]["evidence"]
    assert any(item["rule_id"] == "COOLANT_TEMP_HIGH" for item in evidence)
