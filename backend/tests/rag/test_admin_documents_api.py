"""Admin RAG document-management API tests (hermetic: no pgvector needed).

Covers the API contract, authorization matrix (401/403/admin), upload
validation (400/413/422 + path traversal), listing/detail/delete plumbing and
the parser-registry-driven extension validation. The heavy ingestion paths use
a stub service via ``dependency_overrides``; the pgvector-gated end-to-end
behaviour lives in ``test_admin_documents_integration.py``.
"""

from __future__ import annotations

import io
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.exceptions import NotFoundError
from app.dependencies.database import get_admin_rag_service
from app.main import app
from app.rag.errors import RAGUploadTooLargeError, RAGUploadValidationError
from app.rag.parser import supported_extensions
from app.rag.schemas import RAGDocumentSummary, RAGVersionSummary
from app.schemas.rag import (
    AdminRagDocumentDetailResponse,
    AdminRagUploadResponse,
)

UPLOAD_URL = "/api/v1/admin/rag/documents"


class _FakeAdminRagService:
    """Deterministic stand-in for the admin RAG service."""

    def __init__(
        self,
        *,
        upload: AdminRagUploadResponse | None = None,
        list_rows: tuple[list[RAGDocumentSummary], int] | None = None,
        detail: AdminRagDocumentDetailResponse | None = None,
    ) -> None:
        self._upload_response = upload
        self._list = list_rows or ([], 0)
        self._detail = detail
        self.calls: list[tuple[str, dict]] = []

    async def upload_document(self, **kwargs) -> AdminRagUploadResponse:
        self.calls.append(("upload", kwargs))
        if self._upload_response is None:
            raise RuntimeError("no upload response configured")
        return self._upload_response

    async def list_documents(self, **kwargs) -> tuple[list[RAGDocumentSummary], int]:
        self.calls.append(("list", kwargs))
        return self._list

    async def get_document(self, document_id) -> AdminRagDocumentDetailResponse:
        self.calls.append(("detail", {"document_id": document_id}))
        if self._detail is None:
            raise NotFoundError("RAG document")
        return self._detail

    async def delete_document(self, document_id) -> None:
        self.calls.append(("delete", {"document_id": document_id}))


@pytest.fixture
def fake_service() -> _FakeAdminRagService:
    version = RAGVersionSummary(
        id=uuid4(),
        document_id=uuid4(),
        version=1,
        content_hash="abc",
        source_filename="manual.md",
        parser_name="plain-text",
        embedding_model="phase-5-stub",
        embedding_dimension=1024,
        chunking_version="structural-1.0.0",
        ingestion_status="completed",
        created_at="2026-09-25T00:00:00Z",
        chunk_count=3,
    )
    return _FakeAdminRagService(
        upload=AdminRagUploadResponse(
            id=uuid4(),
            status="ingested",
            filename="manual.md",
            canonical="rep://toyota/camry/2024",
            make="Toyota",
            model="Camry",
            year=2024,
            version=1,
            chunks_created=3,
        ),
        list_rows=(
            [
                RAGDocumentSummary(
                    id=uuid4(),
                    source_type="manufacturer",
                    canonical_source="rep://toyota/camry/2024",
                    make="Toyota",
                    model="Camry",
                    document_type="service-manual",
                    title="Manual",
                    created_at="2026-09-25T00:00:00Z",
                    updated_at="2026-09-25T00:00:00Z",
                    version_count=1,
                )
            ],
            1,
        ),
        detail=AdminRagDocumentDetailResponse(
            id=uuid4(),
            source_type="manufacturer",
            canonical_source="rep://toyota/camry/2024",
            make="Toyota",
            model="Camry",
            document_type="service-manual",
            title="Manual",
            created_at="2026-09-25T00:00:00Z",
            updated_at="2026-09-25T00:00:00Z",
            version_count=1,
            versions=[version],
            latest_version=version,
        ),
    )


def _override_service(fake: _FakeAdminRagService) -> None:
    app.dependency_overrides[get_admin_rag_service] = lambda: fake


def _reset_overrides() -> None:
    app.dependency_overrides.pop(get_admin_rag_service, None)


def _form(files: tuple[str, bytes], **extra) -> dict:
    data = {
        "canonical": "rep://toyota/camry/2024",
        "make": "Toyota",
        "model": "Camry",
        "year": "2024",
        **extra,
    }
    return {
        "files": {"file": files},
        "data": data,
    }


def _markdown() -> tuple[str, bytes]:
    return (
        "service_manual.md",
        b"# Coolant Level\nCheck the reservoir between FULL and LOW.\n",
        "text/markdown",
    )


# --------------------------------------------------------------- auth matrix


async def test_upload_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.post(UPLOAD_URL, **_form(_markdown()))
    assert response.status_code == 401


async def test_upload_requires_admin(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post(UPLOAD_URL, **_form(_markdown()))
    assert response.status_code == 403


async def test_list_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get(UPLOAD_URL)).status_code == 401


async def test_list_requires_admin(auth_client: httpx.AsyncClient) -> None:
    assert (await auth_client.get(UPLOAD_URL)).status_code == 403


async def test_detail_requires_admin(auth_client: httpx.AsyncClient) -> None:
    assert (await auth_client.get(f"{UPLOAD_URL}/{uuid4()}")).status_code == 403


async def test_delete_requires_admin(auth_client: httpx.AsyncClient) -> None:
    assert (await auth_client.delete(f"{UPLOAD_URL}/{uuid4()}")).status_code == 403


# ---------------------------------------------------------------- happy path


async def test_admin_upload_succeeds(admin_client: httpx.AsyncClient, fake_service) -> None:
    _override_service(fake_service)
    try:
        response = await admin_client.post(UPLOAD_URL, **_form(_markdown()))
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "ingested"
        assert body["filename"] == "manual.md"
        assert body["canonical"] == "rep://toyota/camry/2024"
        assert body["make"] == "Toyota"
        assert body["chunks_created"] == 3
        called = fake_service.calls[0]
        assert called[0] == "upload"
        assert called[1]["meta"].canonical == "rep://toyota/camry/2024"
        assert called[1]["filename"] == "service_manual.md"
    finally:
        _reset_overrides()


@pytest.mark.parametrize(
    "suffix",
    [
        ".pdf",
        ".docx",
        ".doc",
        ".rtf",
        ".pptx",
        ".html",
        ".xlsx",
        ".odt",
        ".epub",
        ".txt",
        ".md",
        ".text",
    ],
)
async def test_admin_upload_routes_all_registry_extensions(
    admin_client: httpx.AsyncClient, fake_service, suffix: str
) -> None:
    _override_service(fake_service)
    try:
        response = await admin_client.post(
            UPLOAD_URL,
            **_form(
                (
                    f"doc{suffix}",
                    b"# Heading\nbody\n"[: min(10 + len(suffix), 200)],
                    "application/octet-stream",
                )
            ),
        )
        assert response.status_code == 201, response.text
    finally:
        _reset_overrides()


async def test_admin_list_paginated(admin_client: httpx.AsyncClient, fake_service) -> None:
    _override_service(fake_service)
    try:
        response = await admin_client.get(
            UPLOAD_URL, params={"page": 2, "page_size": 5, "make": "Toyota"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 2
        assert body["page_size"] == 5
        assert body["total"] == 1
        assert body["items"][0]["make"] == "Toyota"
        assert fake_service.calls[0][1]["page"] == 2
    finally:
        _reset_overrides()


async def test_admin_detail_returns_versions(admin_client: httpx.AsyncClient, fake_service) -> None:
    _override_service(fake_service)
    try:
        response = await admin_client.get(f"{UPLOAD_URL}/{uuid4()}")
        assert response.status_code == 200
        body = response.json()
        assert body["latest_version"]["ingestion_status"] == "completed"
        assert body["versions"][0]["chunk_count"] == 3
    finally:
        _reset_overrides()


async def test_detail_missing_returns_404(admin_client: httpx.AsyncClient, fake_service) -> None:
    fake_service._detail = None
    _override_service(fake_service)
    try:
        response = await admin_client.get(f"{UPLOAD_URL}/{uuid4()}")
        assert response.status_code == 404
    finally:
        _reset_overrides()


async def test_admin_delete_returns_204(admin_client: httpx.AsyncClient, fake_service) -> None:
    _override_service(fake_service)
    try:
        response = await admin_client.delete(f"{UPLOAD_URL}/{uuid4()}")
        assert response.status_code == 204
    finally:
        _reset_overrides()


# ----------------------------------------------------- validation (real service)


async def test_unsupported_extension_rejected_400(admin_client: httpx.AsyncClient) -> None:
    response = await admin_client.post(
        UPLOAD_URL, **_form(("manual.xyz", b"data", "application/octet-stream"))
    )
    assert response.status_code == 400
    assert "unsupported document format" in response.json()["detail"]


async def test_empty_file_rejected_400(admin_client: httpx.AsyncClient) -> None:
    response = await admin_client.post(UPLOAD_URL, **_form(("manual.md", b"", "text/markdown")))
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


@pytest.mark.parametrize(
    "name", ["../../secret.txt", "..\\..\\secret.txt", "/etc/passwd", "a/b.txt"]
)
async def test_path_traversal_filename_rejected_400(
    admin_client: httpx.AsyncClient, name: str
) -> None:
    response = await admin_client.post(
        UPLOAD_URL, **_form((name, b"# Heading\nbody\n", "text/markdown"))
    )
    assert response.status_code == 400
    assert "filename" in response.json()["detail"]


async def test_file_part_without_filename_returns_422(admin_client: httpx.AsyncClient) -> None:
    """A plain form value posted to ``file`` is a client error, not a 500."""
    data = {
        "data": {"canonical": "rep://x"},
        "files": {"file": ("", b"# h\nbody\n", "text/markdown")},
    }
    response = await admin_client.post(UPLOAD_URL, **data)
    assert response.status_code == 422


async def test_missing_canonical_rejected_422(admin_client: httpx.AsyncClient) -> None:
    data = {"files": {"file": _markdown()}, "data": {"make": "Toyota"}}
    response = await admin_client.post(UPLOAD_URL, **data)
    assert response.status_code == 422


async def test_extra_form_field_rejected_422(admin_client: httpx.AsyncClient) -> None:
    response = await admin_client.post(UPLOAD_URL, **_form(_markdown(), role="admin"))
    assert response.status_code == 422


async def test_non_utf8_text_rejected_400(admin_client: httpx.AsyncClient) -> None:
    response = await admin_client.post(
        UPLOAD_URL, **_form(("manual.md", b"# h\n\xff\xfe invalid\n", "text/markdown"))
    )
    assert response.status_code == 400


async def test_oversized_upload_rejected_413(
    admin_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.rag.config import get_rag_settings

    monkeypatch.setenv("RAG_MAX_UPLOAD_SIZE_MB", "1")
    get_rag_settings.cache_clear()
    try:
        big = b"x" * (2 * 1024 * 1024)
        response = await admin_client.post(UPLOAD_URL, **_form(("big.txt", big, "text/plain")))
        assert response.status_code == 413
        assert "limit" in response.json()["detail"]
    finally:
        get_rag_settings.cache_clear()


@pytest.mark.skipif(
    __import__("tests").conftest.supports_pgvector(),
    reason="test database has pgvector - RAG tables exist",
)
async def test_list_503_when_rag_unavailable(admin_client: httpx.AsyncClient) -> None:
    response = await admin_client.get(UPLOAD_URL)
    assert response.status_code == 503


# -------------------------------------------------------- parser registry truth


def test_supported_extensions_derived_from_registry() -> None:
    from app.rag.parser.docling import DOCLING_EXTENSIONS, PLAIN_TEXT_EXTENSIONS

    assert supported_extensions() == frozenset(DOCLING_EXTENSIONS | PLAIN_TEXT_EXTENSIONS)
    expected = {
        ".pdf",
        ".docx",
        ".doc",
        ".rtf",
        ".pptx",
        ".ppt",
        ".html",
        ".mhtml",
        ".xlsx",
        ".xls",
        ".odt",
        ".ods",
        ".odp",
        ".epub",
        ".txt",
        ".md",
        ".text",
    }
    assert expected <= set(supported_extensions())


def test_sanitize_filename_guards(tmp_path: Path) -> None:
    from app.rag.admin_documents import _sanitize_filename

    assert _sanitize_filename("manual.PDF") == "manual.PDF"
    assert _sanitize_filename("sub dir.md") == "sub dir.md"
    for bad in (
        "",
        " ",
        "../../secret.txt",
        "..\\..\\secret.txt",
        "/etc/passwd",
        "a\\b.txt",
        "a/b.txt",
        "x\x00y.txt",
    ):
        with pytest.raises(RAGUploadValidationError):
            _sanitize_filename(bad)


class _AsyncBytes:
    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    async def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(b"", RAGUploadValidationError, id="empty"),
        pytest.param(b"x" * (2 * 1024 * 1024), RAGUploadTooLargeError, id="oversized"),
    ],
)
async def test_temp_files_cleaned_on_validation_failure(
    tmp_path: Path, payload: bytes, expected: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.rag.admin_documents import AdminRagDocumentService
    from app.rag.config import get_rag_settings
    from app.schemas.rag import AdminRagDocumentUploadForm

    monkeypatch.setenv("RAG_MAX_UPLOAD_SIZE_MB", "1")
    get_rag_settings.cache_clear()
    try:
        service = AdminRagDocumentService(None, temp_dir=tmp_path)
        form = AdminRagDocumentUploadForm(canonical="rep://tmp")
        with pytest.raises(expected):
            await service.upload_document(filename="doc.txt", file=_AsyncBytes(payload), meta=form)
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("dtwin-rag-")]
        assert leftovers == []
    finally:
        get_rag_settings.cache_clear()
