"""QA simulation: telemetry ingestion safety (TC-01/TC-02/TC-08 evidence).

Exercises the real HTTP API against the isolated test database
(``digital_twin_test`` via ``tests/conftest.py`` — never production):

* TC-01 — valid telemetry is accepted, retrievable, vehicle-bound, timestamped.
* TC-02 — missing fields, wrong types, malformed timestamps, out-of-range
  values and null readings behave per the documented contract.
* TC-08 — auth, unknown vehicles and malformed payloads fail with clean,
  secret-free error envelopes (no tracebacks).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from tests.conftest import unique_vin

VALID_TELEMETRY = {
    "timestamp": "2026-10-14T08:00:00Z",
    "rpm": 2500.0,
    "speed": 60.0,
    "engine_load": 30.0,
    "coolant_temperature": 90.0,
    "oil_temperature": 88.0,
    "battery_voltage": 13.9,
    "fuel_level": 75.0,
    "intake_air_temperature": 30.0,
    "throttle_position": 20.0,
    "engine_runtime": 1000.0,
    "odometer": 45231.7,
}


async def _make_vehicle(auth_client: httpx.AsyncClient) -> str:
    response = await auth_client.post(
        "/api/v1/vehicles",
        json={
            "vin": unique_vin(),
            "make": "Toyota",
            "model": "Corolla",
            "year": 2023,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_tc01_valid_telemetry_round_trip(auth_client: httpx.AsyncClient) -> None:
    vehicle_id = await _make_vehicle(auth_client)

    posted = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", json=VALID_TELEMETRY
    )
    assert posted.status_code == 201, posted.text
    body = posted.json()
    assert body["vehicle_id"] == vehicle_id
    assert body["rpm"] == 2500.0
    assert body["timestamp"] == "2026-10-14T08:00:00Z"

    listed = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/telemetry?page_size=5")
    assert listed.status_code == 200
    page = listed.json()
    assert page["total"] == 1
    assert page["items"][0]["vehicle_id"] == vehicle_id
    assert page["items"][0]["timestamp"] == "2026-10-14T08:00:00Z"


async def test_tc01_unknown_vehicle_is_404(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/vehicles/00000000-0000-4000-8000-000000000000/telemetry",
        json=VALID_TELEMETRY,
    )
    assert response.status_code == 404
    assert "Traceback" not in response.text


async def test_tc01_empty_telemetry_list_is_200_with_total_zero(
    auth_client: httpx.AsyncClient,
) -> None:
    vehicle_id = await _make_vehicle(auth_client)
    response = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/telemetry")
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


async def test_tc02_missing_timestamp_is_422(auth_client: httpx.AsyncClient) -> None:
    vehicle_id = await _make_vehicle(auth_client)
    payload = dict(VALID_TELEMETRY)
    del payload["timestamp"]
    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload
    )
    assert response.status_code == 422


async def test_tc02_wrong_type_is_422(auth_client: httpx.AsyncClient) -> None:
    vehicle_id = await _make_vehicle(auth_client)
    payload = dict(VALID_TELEMETRY, rpm="fast")
    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload
    )
    assert response.status_code == 422


async def test_tc02_malformed_timestamp_is_422(auth_client: httpx.AsyncClient) -> None:
    vehicle_id = await _make_vehicle(auth_client)
    payload = dict(VALID_TELEMETRY, timestamp="not-a-timestamp")
    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload
    )
    assert response.status_code == 422


async def test_tc02_out_of_range_is_422(auth_client: httpx.AsyncClient) -> None:
    vehicle_id = await _make_vehicle(auth_client)
    for payload in (
        dict(VALID_TELEMETRY, rpm=-5.0),
        dict(VALID_TELEMETRY, coolant_temperature=500.0),
        dict(VALID_TELEMETRY, fuel_level=101.0),
    ):
        response = await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload
        )
        assert response.status_code == 422, payload


async def test_tc02_unknown_field_is_rejected(auth_client: httpx.AsyncClient) -> None:
    vehicle_id = await _make_vehicle(auth_client)
    payload = dict(VALID_TELEMETRY, warp_drive=9.0)
    response = await auth_client.post(
        f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload
    )
    assert response.status_code == 422


async def test_tc02_null_readings_and_out_of_order_persist(
    auth_client: httpx.AsyncClient,
) -> None:
    """Nulls are stored as null (no fabrication); rows order by timestamp, not
    insert order."""
    vehicle_id = await _make_vehicle(auth_client)
    base = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    first = dict(
        VALID_TELEMETRY,
        timestamp=(base + timedelta(seconds=20)).isoformat(),
        rpm=None,
        coolant_temperature=None,
    )
    second = dict(VALID_TELEMETRY, timestamp=base.isoformat())
    for payload in (first, second):  # newest persisted first on purpose
        response = await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload
        )
        assert response.status_code == 201, response.text

    listed = await auth_client.get(f"/api/v1/vehicles/{vehicle_id}/telemetry?page_size=5")
    items = listed.json()["items"]
    assert [item["timestamp"] for item in items] == [
        "2026-10-14T08:00:20Z",
        "2026-10-14T08:00:00Z",
    ]
    assert items[0]["rpm"] is None
    assert items[0]["coolant_temperature"] is None


async def test_tc08_unauthenticated_telemetry_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/vehicles/00000000-0000-4000-8000-000000000000/telemetry"
    )
    assert response.status_code == 401, response.status_code
    assert "Traceback" not in response.text
    response = await client.post(
        "/api/v1/vehicles/00000000-0000-4000-8000-000000000000/telemetry",
        json=VALID_TELEMETRY,
    )
    assert response.status_code == 401, response.status_code
    assert "Traceback" not in response.text


async def test_tc08_other_owners_vehicle_is_not_visible(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    vehicle_id = await _make_vehicle(auth_client)
    response = await other_user_client.get(f"/api/v1/vehicles/{vehicle_id}/telemetry")
    assert response.status_code in (403, 404)
    assert "Traceback" not in response.text


async def test_tc08_rag_disabled_reports_degraded_503(
    auth_client: httpx.AsyncClient,
) -> None:
    """The test harness forces RAG off: search must say so explicitly."""
    response = await auth_client.get("/api/v1/rag/search", params={"q": "coolant"})
    assert response.status_code == 503
    assert "Traceback" not in response.text
