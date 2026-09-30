"""Phase 6 authorization matrix: role + ownership enforcement across routes.

Matrix covered:
  - unauthenticated request → 401 on every protected resource
  - authenticated non-owner → 404 on owner-scoped resources (no IDOR leak)
  - authenticated owner → 2xx/4xx as appropriate
  - admin → full access to any vehicle
"""

from __future__ import annotations

import uuid

import httpx


async def test_unauth_all_protected_routes_return_401(
    client: httpx.AsyncClient,
) -> None:
    uid = str(uuid.uuid4())
    routes = [
        ("GET", "/api/v1/vehicles"),
        ("GET", f"/api/v1/vehicles/{uid}"),
        ("GET", f"/api/v1/vehicles/{uid}/telemetry"),
        ("GET", f"/api/v1/vehicles/{uid}/health"),
        ("GET", f"/api/v1/vehicles/{uid}/agent/diagnoses"),
        ("GET", "/api/v1/rag/search?q=test"),
        ("GET", "/api/v1/rag/health"),
        ("GET", "/api/v1/auth/me"),
    ]
    for method, url in routes:
        response = await client.request(method, url)
        assert response.status_code == 401, (method, url, response.status_code)


async def test_owner_cross_vehicle_matrix(
    auth_client: httpx.AsyncClient,
    other_user_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    """Non-owners get 404 (not 403) for every owner-scoped operation."""
    vehicle_id = sample_vehicle["id"]
    actions = [
        ("GET", f"/api/v1/vehicles/{vehicle_id}"),
        ("GET", f"/api/v1/vehicles/{vehicle_id}/telemetry"),
        ("GET", f"/api/v1/vehicles/{vehicle_id}/health"),
        ("GET", f"/api/v1/vehicles/{vehicle_id}/agent/dashboard"),
        ("GET", f"/api/v1/vehicles/{vehicle_id}/agent/diagnoses"),
    ]
    for method, url in actions:
        response = await other_user_client.request(method, url)
        assert response.status_code == 404, (method, url, response.status_code)

    # Mutations by a non-owner are equally hidden.
    assert (
        await other_user_client.patch(f"/api/v1/vehicles/{vehicle_id}", json={"make": "Honda"})
    ).status_code == 404
    assert (await other_user_client.delete(f"/api/v1/vehicles/{vehicle_id}")).status_code == 404

    # The owner still sees everything.
    assert (await auth_client.get(f"/api/v1/vehicles/{vehicle_id}")).status_code == 200


async def test_admin_can_access_any_vehicle(
    auth_client: httpx.AsyncClient,
    admin_client: httpx.AsyncClient,
    sample_vehicle: dict,
) -> None:
    vehicle_id = sample_vehicle["id"]
    assert (await admin_client.get(f"/api/v1/vehicles/{vehicle_id}")).status_code == 200
    assert (await admin_client.get(f"/api/v1/vehicles/{vehicle_id}/telemetry")).status_code == 200

    listing = await admin_client.get("/api/v1/vehicles")
    assert listing.status_code == 200
    ids = {item["id"] for item in listing.json()["items"]}
    assert vehicle_id in ids


async def test_rag_health_admin_only(
    auth_client: httpx.AsyncClient,
    admin_client: httpx.AsyncClient,
) -> None:
    assert (await auth_client.get("/api/v1/rag/health")).status_code == 403
    assert (await admin_client.get("/api/v1/rag/health")).status_code == 200


async def test_rag_search_allows_any_authenticated_user(
    auth_client: httpx.AsyncClient,
    admin_client: httpx.AsyncClient,
) -> None:
    # RAG is disabled in test env, so both roles get the same 503 explicitly.
    for c in (auth_client, admin_client):
        response = await c.get("/api/v1/rag/search", params={"q": "coolant"})
        assert response.status_code == 503
        assert "disabled" in response.json()["detail"]


async def test_users_me_returns_own_profile(
    auth_client: httpx.AsyncClient,
    auth_user: dict,
) -> None:
    response = await auth_client.get("/api/v1/users/me")
    assert response.status_code == 200
    assert response.json()["email"] == auth_user["email"]


async def test_users_me_patch_updates_full_name(
    auth_client: httpx.AsyncClient,
) -> None:
    patch = await auth_client.patch("/api/v1/users/me", json={"full_name": "New Name"})
    assert patch.status_code == 200
    assert patch.json()["full_name"] == "New Name"

    response = await auth_client.get("/api/v1/users/me")
    assert response.json()["full_name"] == "New Name"


async def test_users_me_cannot_change_email_or_role(
    auth_client: httpx.AsyncClient,
    auth_user: dict,
) -> None:
    patch = await auth_client.patch(
        "/api/v1/users/me",
        json={"email": "hacked@example.com", "role": "admin", "full_name": "Sneaky"},
    )
    # Unknown fields are rejected outright so they can never leak through.
    assert patch.status_code == 422
