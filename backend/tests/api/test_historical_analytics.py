"""API tests for historical analytics: presets, custom ranges, timezone
validation, reversed-range rejection, aggregation shape, run segments and
ownership isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

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


async def _ingest_window(
    auth_client: httpx.AsyncClient,
    vehicle_id: str,
    *,
    count: int = 30,
    start: datetime,
    step_seconds: float = 10.0,
    run_id: str | None = None,
) -> None:
    for index in range(count):
        payload = {
            "timestamp": (start + timedelta(seconds=index * step_seconds)).isoformat(),
            **HEALTHY_PAYLOAD,
        }
        if run_id is not None:
            payload["simulation_run_id"] = run_id
        response = await auth_client.post(
            f"/api/v1/vehicles/{vehicle_id}/telemetry", json=payload
        )
        assert response.status_code == 201, response.text


def _querystring(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None}


async def test_historical_analytics_24h_preset_shape(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    start = datetime.now(UTC) - timedelta(minutes=30)
    await _ingest_window(
        auth_client, vehicle_id, count=20, start=start, step_seconds=5.0, run_id=str(uuid4())
    )

    response = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/historical-analytics", params={"range": "24h"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vehicle_id"] == vehicle_id
    assert body["range"] == "24h"
    assert body["timezone"] == "UTC"
    assert body["total_samples"] >= 20
    assert body["window_start"] < body["window_end"]
    assert body["earliest_sample_at"] is not None
    assert body["latest_sample_at"] is not None

    rpm = next(m for m in body["metrics"] if m["metric"] == "rpm")
    assert rpm["valid_samples"] >= 20
    assert rpm["min_value"] == 2000.0
    assert rpm["max_value"] == 2000.0
    assert rpm["mean_value"] == 2000.0
    assert rpm["median_value"] == 2000.0
    assert rpm["stddev_value"] == 0.0
    assert rpm["delta_value"] == 0.0

    assert len(body["run_segments"]) == 1
    segment = body["run_segments"][0]
    assert segment["run_id"] is not None
    assert segment["samples"] >= 20
    assert segment["is_legacy"] is False
    assert body["buckets"]
    assert body["gaps"]["gap_count"] >= 0
    for bucket in body["buckets"]:
        assert bucket["bucket_start"] < bucket["bucket_end"]


async def test_historical_analytics_run_segment_boundaries(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    """Two distinct runs plus legacy rows resolve into three segments."""
    vehicle_id = sample_vehicle["id"]
    now = datetime.now(UTC)
    run_a, run_b = str(uuid4()), str(uuid4())
    await _ingest_window(
        auth_client, vehicle_id, count=5, start=now - timedelta(minutes=20), step_seconds=5.0, run_id=run_a
    )
    await _ingest_window(
        auth_client, vehicle_id, count=5, start=now - timedelta(minutes=9), step_seconds=5.0, run_id=run_b
    )
    await _ingest_window(
        auth_client, vehicle_id, count=5, start=now - timedelta(minutes=4), step_seconds=5.0
    )

    response = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/historical-analytics", params={"range": "24h"}
    )
    assert response.status_code == 200, response.text
    segments = response.json()["run_segments"]
    assert len(segments) == 3
    by_run = {s["run_id"]: s for s in segments}
    assert by_run[run_a]["samples"] == 5
    assert by_run[run_b]["samples"] == 5
    assert sum(s["samples"] for s in segments if s["is_legacy"]) == 5
    # Segments are ordered by their first sample (oldest run first).
    assert segments[0]["first_timestamp"] < segments[1]["first_timestamp"]


async def test_historical_analytics_custom_range_requires_aware_times(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    now = datetime.now(UTC)
    base = f"/api/v1/vehicles/{vehicle_id}/historical-analytics"

    # Missing start/end for custom -> 422.
    response = await auth_client.get(base, params={"range": "custom"})
    assert response.status_code == 422

    # Reversed range -> 422.
    params = {
        "range": "custom",
        "start_time": (now + timedelta(hours=1)).isoformat(),
        "end_time": now.isoformat(),
    }
    response = await auth_client.get(base, params=_querystring(params))
    assert response.status_code == 422

    # Naive datetimes -> 422.
    naive = now.replace(tzinfo=None)
    params = {
        "range": "custom",
        "start_time": (naive - timedelta(hours=1)).isoformat(),
        "end_time": naive.isoformat(),
    }
    response = await auth_client.get(base, params=_querystring(params))
    assert response.status_code == 422

    # Unknown timezone -> 422.
    params = {
        "range": "24h",
        "timezone": "Not/AZone",
    }
    response = await auth_client.get(base, params=_querystring(params))
    assert response.status_code == 422


async def test_historical_analytics_custom_range_aggregates_window(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    vehicle_id = sample_vehicle["id"]
    now = datetime.now(UTC)
    start = now - timedelta(minutes=60)
    await _ingest_window(
        auth_client, vehicle_id, count=10, start=start, step_seconds=30.0, run_id=str(uuid4())
    )

    response = await auth_client.get(
        f"/api/v1/vehicles/{vehicle_id}/historical-analytics",
        params={
            "range": "custom",
            "start_time": (now - timedelta(minutes=90)).isoformat(),
            "end_time": (now - timedelta(minutes=30)).isoformat(),
            "timezone": "America/New_York",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["range"] == "custom"
    assert body["timezone"] == "America/New_York"
    assert body["total_samples"] == 10
    assert body["duration_seconds"] == pytest.approx(3600, abs=1)
    # The window [now-90m, now-30m] excludes samples at [now-60m..now-30m)... all
    # 10 samples fit inside at 30s steps starting now-60m.
    assert all(b["bucket_start"] >= body["window_start"] for b in body["buckets"])


async def test_historical_analytics_empty_window(
    auth_client: httpx.AsyncClient, sample_vehicle: dict
) -> None:
    response = await auth_client.get(
        f"/api/v1/vehicles/{sample_vehicle['id']}/historical-analytics",
        params={"range": "24h"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_samples"] == 0
    assert body["earliest_sample_at"] is None
    assert body["metrics"] and all(m["valid_samples"] == 0 for m in body["metrics"])
    assert body["run_segments"] == []
    assert body["buckets"] == []
    assert body["snapshots_present"] is False


async def test_historical_analytics_denied_for_other_user(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    vehicle_id = sample_vehicle["id"]
    await _ingest_window(auth_client, vehicle_id, count=3, start=datetime.now(UTC))

    response = await other_user_client.get(
        f"/api/v1/vehicles/{vehicle_id}/historical-analytics", params={"range": "24h"}
    )
    assert response.status_code == 404


async def test_historical_analytics_missing_vehicle_is_404(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await auth_client.get(
        f"/api/v1/vehicles/{uuid4()}/historical-analytics", params={"range": "24h"}
    )
    assert response.status_code == 404
