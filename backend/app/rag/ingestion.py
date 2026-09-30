"""Idempotent corpus ingestion with immutable versioning (Phase 5).

Pipeline per source file:

    parse -> canonical text -> content hash -> version (pending)
          -> structure-aware chunking -> embed -> persist chunks
          -> version (completed)

Guarantees
----------
* **Idempotent:** re-ingesting a file whose latest *completed* version has the
  same content hash is a no-op (``status="unchanged"``).
* **Immutable versions:** identical content never overwrites a completed
  version; a new version number is minted instead. A retried *failed* version
  with the same hash is reused (its orphaned chunks are cleared) so retries do
  not accumulate garbage.
* **Failure-state preservation:** any mid-pipeline failure marks the version
  ``failed`` with the error message and leaves the partial rows visible to
  diagnostics — nothing is silently half-written as ``completed``.
* **No silent fallbacks:** ``.pdf`` (and other Docling types) go through
  Docling and fail loudly if the parser is unavailable; unsupported extensions
  are reported as failures, not guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.rag.chunking import CHUNKING_VERSION, chunk_by_structure
from app.rag.config import get_rag_settings
from app.rag.embeddings import EmbeddingAdapter, get_embedding_adapter
from app.rag.parser.base import sha256_hex
from app.rag.parser.docling import get_parser_for
from app.rag.repository import ChunkRow, RagRepository
from app.rag.schemas import VehicleScope


@dataclass
class IngestionReport:
    """Result of one ``ingest`` call (never raises for file-level failures)."""

    source: str
    canonical_source: str
    document_id: UUID | None = None
    version_id: UUID | None = None
    version: int | None = None
    status: str = "failed"  # ingested | unchanged | failed
    chunk_count: int = 0
    parser_name: str = ""
    embedding_model: str = ""
    embedding_dimension: int = 0
    content_hash: str = ""
    error: str | None = None


class IngestionService:
    """Parses, chunks, embeds and persists one manufacturer document."""

    def __init__(
        self,
        *,
        embedding_adapter: EmbeddingAdapter | None = None,
        stub_embeddings: bool = False,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        chunking_version: str = CHUNKING_VERSION,
    ) -> None:
        settings = get_rag_settings()
        self._embedding = embedding_adapter
        self._stub_embeddings = stub_embeddings
        self.chunk_size = chunk_size or settings.rag_chunk_size
        self.chunk_overlap = (
            chunk_overlap if chunk_overlap is not None else settings.rag_chunk_overlap
        )
        self.chunking_version = chunking_version

    def _embedding_adapter(self) -> EmbeddingAdapter:
        if self._embedding is None:
            self._embedding = get_embedding_adapter(force_stub=self._stub_embeddings)
        return self._embedding

    async def ingest(
        self,
        conn,
        path: Path,
        *,
        canonical_source: str,
        title: str | None = None,
        source_uri: str | None = None,
        source_type: str = "manufacturer",
        manufacturer: str | None = None,
        make: str | None = None,
        model: str | None = None,
        year_start: int | None = None,
        year_end: int | None = None,
        document_type: str = "service-manual",
        language: str | None = "en",
    ) -> IngestionReport:
        """Ingest ``path`` and report what happened (no file-level raise)."""
        settings = get_rag_settings()
        path = Path(path)
        scope = VehicleScope(make=make, model=model, year=year_start or year_end)
        report = IngestionReport(
            source=str(path),
            canonical_source=canonical_source,
            content_hash="",
        )
        if not path.is_file():
            report.error = f"source file not found: {path}"
            return report
        if path.stat().st_size > settings.rag_max_document_bytes:
            report.error = (
                f"{path.name} exceeds the {settings.rag_max_document_bytes}-byte ingest limit"
            )
            return report

        try:
            parser = get_parser_for(path)
            parse_result = parser.parse(path)
        except Exception as exc:  # noqa: BLE001 - parser is downstream, report it
            report.error = f"parse failed ({exc.__class__.__name__}): {exc}"
            report.parser_name = getattr(parser, "name", "?") if "parser" in locals() else "?"
            return report

        report.parser_name = getattr(parser, "name", "?")
        text = (parse_result.text or "").strip()
        content_hash = parse_result.content_hash or sha256_hex(parse_result.text or "")
        report.content_hash = content_hash
        if not text:
            report.error = "empty canonical text; nothing to index"
            return report

        adapter = self._embedding_adapter()
        repo = RagRepository(conn)

        try:
            doc_id = await self._ensure_document(
                repo,
                canonical_source,
                title=title or path.stem,
                source_uri=source_uri,
                source_type=source_type,
                manufacturer=manufacturer,
                make=make,
                model=model,
                year_start=year_start,
                year_end=year_end,
                document_type=document_type,
                language=language,
            )
            report.document_id = doc_id

            version_id, version_no, must_ingest = await self._resolve_version(
                repo, doc_id, content_hash
            )
            report.version_id = version_id
            report.version = version_no
            if not must_ingest:
                report.status = "unchanged"
                return report

            await repo.insert_version(
                version_id,
                doc_id,
                version=version_no,
                content_hash=content_hash,
                source_filename=path.name,
                parser_name=getattr(parser, "name", "?"),
                parser_version=getattr(parser, "version", None),
                language=language,
                page_count=parse_result.page_count,
                embedding_model=adapter.name,
                embedding_dimension=adapter.dimension,
                chunking_version=self.chunking_version,
                metadata={
                    "source_type": source_type,
                    "document_type": document_type,
                    "make": make,
                    "model": model,
                    "year_start": year_start,
                    "year_end": year_end,
                    "pages": parse_result.pages,
                },
            )

            chunks = chunk_by_structure(
                parse_result.text,
                size=self.chunk_size,
                overlap=self.chunk_overlap,
            )
            if len(chunks) > settings.rag_max_chunks:
                raise ValueError(f"{len(chunks)} chunks exceed the {settings.rag_max_chunks} cap")

            contents = [c.content for c in chunks]
            vectors = adapter.encode(contents, normalize=True)
            if getattr(vectors, "shape", (len(contents),))[1] != adapter.dimension:
                raise ValueError(
                    f"adapter {adapter.name!r} produced {vectors.shape[1]}-dim vectors; "
                    f"expected {adapter.dimension}"
                )

            await repo.delete_chunks_for_version(version_id)
            for i, chunk in enumerate(chunks):
                await repo.insert_chunk(
                    ChunkRow(
                        chunk_id=uuid4(),
                        document_version_id=version_id,
                        chunk_index=chunk.chunk_index,
                        chunk_type=chunk.chunk_type,
                        title=chunk.title,
                        section_title=chunk.section_title,
                        heading_path=chunk.heading_path,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        start_char=chunk.start_char,
                        end_char=chunk.end_char,
                        content=chunk.content,
                        scope_make=scope.make,
                        scope_model=scope.model,
                        scope_year=scope.year,
                    ),
                    vectors[i],
                )

            await repo.complete_version(version_id)
            report.status = "ingested"
            report.chunk_count = len(chunks)
            report.embedding_model = adapter.name
            report.embedding_dimension = adapter.dimension
            return report
        except Exception as exc:  # noqa: BLE001 - report, preserve state
            msg = f"{exc.__class__.__name__}: {exc}"
            if report.version_id is not None:
                try:
                    await repo.fail_version(report.version_id, msg)
                except Exception:  # noqa: BLE001 - connection may be broken
                    pass
            report.error = msg
            report.status = "failed"
            return report

    @staticmethod
    async def _ensure_document(repo: RagRepository, canonical_source: str, **cols: Any) -> UUID:
        existing = await repo.get_document(canonical_source)
        if existing:
            return existing["id"]
        return await repo.upsert_document(uuid4(), canonical_source, **cols)

    @staticmethod
    async def _resolve_version(
        repo: RagRepository, doc_id: UUID, content_hash: str
    ) -> tuple[UUID, int, bool]:
        """Return ``(version_id, version_no, must_ingest)`` with immutability."""
        latest = await repo.latest_version(doc_id)
        if latest and latest["content_hash"] == content_hash:
            if latest["ingestion_status"] == "completed":
                return latest["id"], latest["version"], False
            # Reuse the failed/pending version so retries stay immutable.
            return latest["id"], latest["version"], True
        if latest:
            return uuid4(), latest["version"] + 1, True
        return uuid4(), 1, True
