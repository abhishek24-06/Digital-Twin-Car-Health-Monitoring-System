"""Admin document management for the manufacturer RAG corpus (Phase 6.x).

This service is the single API-side entry point that drives the *existing*
Phase 5 ingestion pipeline: parse → structure-aware chunking → BGE-M3
embeddings → pgvector. It deliberately adds **no** second parser/chunker/
embedder — everything below the upload/safety layer is
:class:`~app.rag.ingestion.IngestionService` (the same code the
``ingest_documents.py`` CLI uses).

Responsibilities owned here and only here:

* validate the upload (extension from the parser registry, size limit, empty
  file, MIME sanity for text types, path-traversal-safe filename),
* store the bytes in a throwaway temp file (never under the original name),
* call the existing ingestion service inside the caller's transaction,
* commit on success / roll back on failure,
* always clean the temp file.

Transaction boundary: a successful upload must persist the document, version,
chunks and vector records (the Phase 5 mistake of write-without-commit is not
repeated — session commit/rollback is explicit here).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.exceptions import NotFoundError
from app.rag.config import get_rag_settings
from app.rag.errors import (
    RAGDocumentUnavailableError,
    RAGIngestionFailureError,
    RAGUploadTooLargeError,
    RAGUploadValidationError,
    RAGVectorUnavailableError,
)
from app.rag.ingestion import IngestionReport, IngestionService
from app.rag.parser import supported_extensions
from app.rag.parser.docling import PLAIN_TEXT_EXTENSIONS
from app.rag.repository import RagRepository
from app.rag.schemas import RAGDocumentSummary, RAGVersionSummary
from app.schemas.rag import (
    AdminRagDocumentDetailResponse,
    AdminRagDocumentUploadForm,
    AdminRagUploadResponse,
)

logger = logging.getLogger(__name__)

_CHUNK_READ_SIZE = 1024 * 1024


def _sanitize_filename(filename: str) -> str:
    """Return a storage-safe basename or raise :class:`RAGUploadValidationError`.

    The original filename is kept for metadata only; it is never used as a
    filesystem path. Directory separators, ``..`` traversal and NUL bytes are
    rejected outright so hostile multipart names cannot reach the disk.
    """
    name = (filename or "").strip()
    if not name:
        raise RAGUploadValidationError("missing filename")
    if name != Path(name).name or ".." in name or "\x00" in name:
        raise RAGUploadValidationError("filename must be a plain file name")
    if "/" in name or "\\" in name:
        raise RAGUploadValidationError("filename must be a plain file name")
    return name


def _validate_text(preview: bytes) -> None:
    """UTF-8 sanity for plain-text types (MIME check 'where practical')."""
    try:
        preview.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RAGUploadValidationError("document is not valid UTF-8 text") from exc


def _ingest_metadata(filename: str, meta: AdminRagDocumentUploadForm) -> dict[str, Any]:
    """Map validated metadata onto ``IngestionService.ingest`` kwargs."""
    year_end = meta.year_end
    if year_end is None and meta.year is not None:
        year_end = meta.year
    return {
        "canonical_source": meta.canonical,
        "title": meta.title or Path(filename).stem,
        "source_uri": meta.source_uri,
        "source_type": meta.source_type or "manufacturer",
        "manufacturer": meta.manufacturer,
        "make": meta.make,
        "model": meta.model,
        "year_start": meta.year,
        "year_end": year_end,
        "document_type": meta.document_type or "service-manual",
        "language": meta.language or "en",
    }


class AdminRagDocumentService:
    """HTTP-facing document management for the manufacturer corpus."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        ingestion_factory: Callable[[], IngestionService] | None = None,
        temp_dir: Path | None = None,
    ) -> None:
        self._session = session
        self._ingestion_factory = ingestion_factory or (lambda: IngestionService())
        self._temp_dir = temp_dir

    async def _connection(self) -> AsyncConnection:
        return await self._session.connection()

    async def _repository(self) -> RagRepository:
        return RagRepository(await self._connection())

    # ------------------------------------------------------------------ upload

    async def upload_document(
        self,
        *,
        filename: str,
        file: Any,
        meta: AdminRagDocumentUploadForm,
    ) -> AdminRagUploadResponse:
        """Validate and ingest one uploaded document (raises on failure)."""
        settings = get_rag_settings()
        name = _sanitize_filename(filename)
        ext = Path(name).suffix.lower()
        if ext not in supported_extensions():
            raise RAGUploadValidationError(f"unsupported document format '{ext or '(none)'}'")

        async with self._save_upload(name, file, settings.rag_max_upload_bytes) as saved:
            report = await self._ingest_with_commit(saved, name, meta)
        return _to_upload_response(report, name, meta)

    @asynccontextmanager
    async def _save_upload(self, name: str, file: Any, max_bytes: int) -> AsyncIterator[Path]:
        """Stream the upload to a unique temp file; always clean up.

        The temp dir is created with ``mkdtemp`` (prefixed, outside the
        repository) and the file name is a random hex + extension, so it can
        never collide with or traverse into user paths. Every exit path —
        validation error, size error, ingest success or failure — removes the
        whole temp dir.
        """
        temp_root = Path(
            tempfile.mkdtemp(
                prefix="dtwin-rag-",
                dir=str(self._temp_dir) if self._temp_dir is not None else None,
            )
        )
        try:
            dst = temp_root / f"{uuid4().hex}{Path(name).suffix}"
            size = await _stream_to(dst, file, max_bytes)
            if size == 0:
                raise RAGUploadValidationError("uploaded document is empty")
            if Path(name).suffix.lower() in PLAIN_TEXT_EXTENSIONS:
                _validate_text(dst.read_bytes()[:4096])
            yield dst
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    async def _ingest_with_commit(
        self, path: Path, filename: str, meta: AdminRagDocumentUploadForm
    ) -> IngestionReport:
        conn = await self._connection()
        try:
            health = await RagRepository(conn).health()
        except Exception:  # noqa: BLE001 - degraded state is explicit everywhere
            health = {}
        if not health.get("pgvector_available"):
            raise RAGDocumentUnavailableError("RAG backend unavailable (pgvector missing)")

        service = self._ingestion_factory()
        report = await service.ingest(conn, path, **_ingest_metadata(filename, meta))
        if report.status in {"ingested", "unchanged"}:
            await self._session.commit()
            return report
        await self._session.rollback()
        raise RAGIngestionFailureError(report.error or "document ingestion failed")

    # ------------------------------------------------------------ manage

    async def list_documents(
        self,
        *,
        page: int,
        page_size: int,
        make: str | None = None,
        model: str | None = None,
        year: int | None = None,
        canonical: str | None = None,
        status: str | None = None,
    ) -> tuple[list[RAGDocumentSummary], int]:
        try:
            rows, total = await (await self._repository()).list_documents(
                limit=page_size,
                offset=(page - 1) * page_size,
                make=make,
                model=model,
                year=year,
                canonical=canonical,
                status=status,
            )
        except RAGVectorUnavailableError:
            raise _unavailable() from None
        return [RAGDocumentSummary.model_validate(r) for r in rows], total

    async def get_document(self, document_id: UUID) -> AdminRagDocumentDetailResponse:
        try:
            payload = await (await self._repository()).get_document_detail(document_id)
        except RAGVectorUnavailableError:
            raise _unavailable() from None
        if payload is None:
            raise NotFoundError("RAG document")
        doc = RAGDocumentSummary.model_validate(payload["document"])
        versions = [RAGVersionSummary.model_validate(v) for v in payload["versions"]]
        return AdminRagDocumentDetailResponse(
            **doc.model_dump(),
            versions=versions,
            latest_version=versions[-1] if versions else None,
        )

    async def delete_document(self, document_id: UUID) -> None:
        try:
            deleted = await (await self._repository()).delete_document(document_id)
        except RAGVectorUnavailableError:
            raise _unavailable() from None
        if not deleted:
            raise NotFoundError("RAG document")
        await self._session.commit()


def _unavailable() -> RAGDocumentUnavailableError:
    return RAGDocumentUnavailableError("RAG backend unavailable (pgvector missing)")


async def _stream_to(dst: Path, file: Any, max_bytes: int) -> int:
    """Chunked copy with a hard byte ceiling (never buffers the whole file)."""
    total = 0
    with dst.open("wb") as out:
        while True:
            chunk = await file.read(_CHUNK_READ_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RAGUploadTooLargeError(f"upload exceeds the {max_bytes}-byte limit")
            out.write(chunk)
    return total


def _to_upload_response(
    report: IngestionReport, filename: str, meta: AdminRagDocumentUploadForm
) -> AdminRagUploadResponse:
    return AdminRagUploadResponse(
        id=report.document_id,
        status="ingested" if report.status == "ingested" else "unchanged",
        filename=filename,
        canonical=report.canonical_source,
        make=meta.make,
        model=meta.model,
        year=meta.year,
        version=report.version,
        chunks_created=report.chunk_count,
        content_hash=report.content_hash or "",
        parser_name=report.parser_name,
        embedding_model=report.embedding_model,
        embedding_dimension=report.embedding_dimension,
    )
