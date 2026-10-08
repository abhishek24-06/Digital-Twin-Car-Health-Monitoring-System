"""Phase 6 auth flow tests: register, login, refresh rotation, logout."""

from __future__ import annotations

import httpx

PASSWORD = "Sup3rSecret!"
EMAIL = "alice@example.com"


def _register_payload(**overrides: str) -> dict:
    payload = {"email": EMAIL, "password": PASSWORD, "full_name": "Alice Test"}
    payload.update(overrides)
    return payload


async def test_register_creates_user(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=_register_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert body["full_name"] == "Alice Test"
    assert "password" not in body
    assert body["id"]


async def test_register_normalizes_email(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json=_register_payload(email="  Alice@Example.COM  ")
    )

    assert response.status_code == 201
    assert response.json()["email"] == "alice@example.com"


async def test_register_rejects_duplicate_email(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/register", json=_register_payload())).status_code == 201
    second = await client.post("/api/v1/auth/register", json=_register_payload(email=EMAIL.upper()))

    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


async def test_register_rejects_self_elevation(client: httpx.AsyncClient) -> None:
    """Clients can never set their own role or is_active."""
    response = await client.post(
        "/api/v1/auth/register", json=_register_payload(role="admin", is_active="true")
    )

    assert response.status_code == 422


async def test_register_rejects_weak_password(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=_register_payload(password="short"))

    assert response.status_code == 422


async def test_register_rejects_password_over_72_bytes(client: httpx.AsyncClient) -> None:
    """bcrypt caps input at 72 bytes, so an oversized password is a 422, not a 500."""
    response = await client.post("/api/v1/auth/register", json=_register_payload(password="a" * 73))

    assert response.status_code == 422


async def test_register_rejects_multibyte_password_over_72_bytes(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/auth/register", json=_register_payload(password="💥" * 19)
    )

    assert response.status_code == 422


async def test_register_accepts_exactly_72_ascii_bytes(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=_register_payload(password="a" * 72))

    assert response.status_code == 201


async def test_login_rejects_password_over_72_bytes(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=_register_payload())
    response = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "a" * 73})

    assert response.status_code == 422


async def test_register_rejects_invalid_email(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=_register_payload(email="nope"))

    assert response.status_code == 422


async def test_login_returns_token_pair(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=_register_payload())

    response = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 20 * 60
    assert body["user"]["email"] == EMAIL
    assert body["user"]["role"] == "user"


async def test_login_bad_password_401(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=_register_payload())

    response = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong!"})

    assert response.status_code == 401


async def test_login_unknown_email_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )

    assert response.status_code == 401


async def test_login_does_not_leak_email_existence(client: httpx.AsyncClient) -> None:
    """Bad-email and bad-password responses are byte-identical in status+body."""
    from tests.conftest import _register_and_login

    await _register_and_login(client, email=EMAIL, password=PASSWORD)
    known = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong!"})
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "wrong!"}
    )
    assert known.status_code == unknown.status_code == 401
    assert known.json()["detail"] == unknown.json()["detail"]


async def test_me_endpoint_returns_profile(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["role"] == "user"
    assert response.json()["email"].endswith("@example.com")


async def test_me_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_refresh_rotates_token(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=_register_payload())
    login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"] != refresh_token
    assert body["user"]["email"] == EMAIL

    # The old refresh token is now revoked (rotation).
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401


async def test_logout_revokes_refresh_token(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=_register_payload())
    login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout.status_code == 204

    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401


async def test_logout_is_idempotent(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=_register_payload())
    login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    token = login.json()["refresh_token"]

    assert (
        await client.post("/api/v1/auth/logout", json={"refresh_token": token})
    ).status_code == 204
    # Re-logout, and logout of a bogus token, are both 204.
    assert (
        await client.post("/api/v1/auth/logout", json={"refresh_token": token})
    ).status_code == 204
    assert (
        await client.post("/api/v1/auth/logout", json={"refresh_token": "bogus-token"})
    ).status_code == 204


async def test_refresh_invalid_token_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
    assert response.status_code == 401


async def test_stale_access_token_rejected(client: httpx.AsyncClient) -> None:
    """A token signed with the wrong secret must be rejected."""
    await client.post("/api/v1/auth/register", json=_register_payload())
    login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    access = login.json()["access_token"]

    tampered = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access[:-3]}xxx"}
    )
    assert tampered.status_code == 401


NEW_PASSWORD = "N3wSecret!!"


async def test_change_password_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.patch(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401


async def test_change_password_happy_path(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=_register_payload())
    login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    changed = await client.patch(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert changed.status_code == 204
    assert changed.content == b""  # the hash is never returned
    login_new = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD}
    )
    assert login_new.status_code == 200
    login_old = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login_old.status_code == 401


async def test_change_password_wrong_current_password_401(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await auth_client.patch(
        "/api/v1/auth/password",
        json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401


async def test_change_password_short_new_password_422(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await auth_client.patch(
        "/api/v1/auth/password",
        json={"current_password": "wrong-password", "new_password": "short"},
    )

    assert response.status_code == 422


async def test_change_password_revokes_refresh_tokens(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=_register_payload())
    login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    changed = await client.patch(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 204

    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401
