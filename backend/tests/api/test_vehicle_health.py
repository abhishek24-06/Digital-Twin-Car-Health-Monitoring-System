from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

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


def _payload_at(seconds_ago: float) -> dict:
    ts = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    return {"timestamp": ts, **HEALTHY_PAYLOAD}


async def _ingest(auth_client: httpx.AsyncClient, vehicle_id: str, count: int = 40) -> None:
    for index in range(count):
        response = await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry",
            json=_payload_at(count - index),
        )
        assert response.status_code == 201, response.text


async def test_analyze_creates_healthy_context(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)

    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["vehicle_id"] == vehicle_id
    assert payload["context_schema_version"] == "1.0"
    assert payload["rule_engine_version"] == "1.0"
    assert payload["health_status"] == "healthy"
    assert payload["health_score"] == 100.0
    assert payload["data_quality"]["sample_count"] == 40
    assert "coolant_temperature" in payload["statistics"]
    assert isinstance(payload["confidence"], float)


async def test_get_latest_returns_most_recent_analysis(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health")
    assert response.status_code == 200
    assert response.json()["health_status"] == "healthy"


async def test_get_latest_404_when_no_snapshot(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.get(f"/api/v1/vehicles/{sample_vehicle['id']}/health")
    assert response.status_code == 404


async def test_get_latest_404_for_missing_vehicle(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get(f"/api/v1/vehicles/{uuid4()}/health")
    assert response.status_code == 404


async def test_history_pagination_and_growth(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    for _ in range(3):
        assert (
            await auth_client.post(
                f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
            )
        ).status_code == 200

    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/health/history")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert len(page["items"]) == 3
    items = page["items"]
    assert all(item["health_status"] == "healthy" for item in items)
    assert items[0]["generated_at"] >= items[1]["generated_at"]

    page_two = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/health/history", params={"page": 1, "page_size": 2}
    )
    assert page_two.json()["total"] == 3
    assert len(page_two.json()["items"]) == 2


async def test_history_time_filtering(auth_client: httpx.AsyncClient, sample_vehicle: dict) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    assert (
        await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
        )
    ).status_code == 200

    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    response = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/health/history",
        params={"start_time": future},
    )
    assert response.json()["total"] == 0

    response = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/health/history",
        params={"end_time": past},
    )
    assert response.json()["total"] == 0


async def test_analyze_missing_vehicle_is_404(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post(f"/api/v1/vehicles/{uuid4()}/health/analyze")
    assert response.status_code == 404


async def test_analyze_invalid_window_minutes_is_422(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/health/analyze",
        params={"window_minutes": 0},
    )
    assert response.status_code == 422

    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/health/analyze",
        params={"window_minutes": 1441},
    )
    assert response.status_code == 422


async def test_analyze_with_no_telemetry_is_unknown(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.post(
        f"/api/v1/vehicles/{sample_vehicle['id']}/health/analyze", params={"window_minutes": 1}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["health_status"] == "unknown"
    assert payload["health_score"] is None
    assert any(f["rule_id"] == "INSUFFICIENT_DATA" for f in payload["findings"])


async def test_high_temperature_context_reflected_in_findings(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    for index in range(40):
        payload = _payload_at(40 - index)
        payload["coolant_temperature"] = 115.0
        response = await auth_client.post(f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload)
        assert response.status_code == 201, response.text

    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
    )
    assert response.status_code == 200
    payload = response.json()
    rule_ids = {f["rule_id"]: f["severity"] for f in payload["findings"]}
    assert rule_ids["COOLANT_TEMP_HIGH"] == "critical"
    assert payload["health_status"] == "attention"


async def test_cross_user_health_denied(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest(auth_client, vehicle_id)
    assert (
        await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
        )
    ).status_code == 200

    assert (await other_user_client.get(f"/api/v1/vehicles/{vehicle_id}/health")).status_code == 404
    assert (
        await other_user_client.get(f"/api/v1/vehicles/{vehicle_id}/health/history")
    ).status_code == 404
    assert (
        await other_user_client.post(
            f"/api/v1/vehicles/{vehicle_id}/health/analyze", params={"window_minutes": 1}
        )
    ).status_code == 404
