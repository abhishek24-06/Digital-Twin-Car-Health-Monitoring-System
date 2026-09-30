"""Read-only RAG admin API tests (hermetic: RAG disabled in test env).

``/rag/health`` is admin-only; ``/rag/search`` requires any authenticated user.
"""

from __future__ import annotations

import httpx


async def test_rag_health_reports_disabled_state(admin_client: httpx.AsyncClient) -> None:
    response = await admin_client.get("/api/v1/rag/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["rag_enabled"] is False
    assert "pgvector_available" in payload
    assert "corpus_documents" in payload


async def test_rag_health_requires_admin(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/rag/health")
    assert response.status_code == 403


async def test_rag_health_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/rag/health")
    assert response.status_code == 401


async def test_rag_search_refuses_when_disabled(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get(
        "/api/v1/rag/search",
        params={"q": "coolant temperature high", "make": "Toyota"},
    )
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


async def test_rag_search_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/rag/search", params={"q": "coolant"})
    assert response.status_code == 401


async def test_rag_search_rejects_empty_query(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/rag/search", params={"q": ""})
    assert response.status_code == 422
