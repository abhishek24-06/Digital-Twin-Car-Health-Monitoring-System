"""Raw-SQL pgvector/FTS repository for the Phase 5 RAG corpus.

Deliberately raw SQL: the hybrid dense+lexical query lives in one place with
exact, explicit parameter binding against the schema created by migration
``4f9d3c2b1a8e`` (source of truth: :mod:`app.models.rag`).

Every corpus-touching method is ``async`` and runs on the caller's open
:class:`~sqlalchemy.ext.asyncio.AsyncConnection`, so ingestion/retrieval can be
embedded in the caller's transaction. Retrieval only ever reads *completed*
versions; embeddings are stored in ``embedding_store`` (``vector(1024)``) and
populated by the ingestion layer (``to_tsvector('english', …)`` keeps
``content_tsv`` in sync at the DB).

An embedding is passed to the repository as a Python sequence of floats; it is
rendered as a pgvector ``vector`` literal (``"[0.1, 0.2, …]"``) so no asyncpg
codec registration is required.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.rag.config import get_rag_settings
from app.rag.errors import RAGVectorUnavailableError
from app.rag.schemas import (
    RetrievedEvidence,
    VehicleScope,
)
from app.rag.scope import derive_tier


def vector_literal(values: Sequence[float]) -> str:
    """Render a float sequence as a pgvector literal (``"[…]"``)."""
    return "[" + ",".join(format(float(x), ".8g") for x in values) + "]"


@dataclass(frozen=True)
class ChunkRow:
    """One vectorised chunk row (everything except the embedding itself)."""

    chunk_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_index: int
    chunk_type: str
    title: str
    section_title: str
    heading_path: list[str]
    page_start: int | None = None
    page_end: int | None = None
    start_char: int = 0
    end_char: int = 0
    content: str = ""
    scope_make: str | None = None
    scope_model: str | None = None
    scope_year: int | None = None


_SCOPE_FILTER = """
  (CAST(:vmake AS text) is null or c.make is null or c.make = CAST(:vmake AS text))
  and (CAST(:vmodel AS text) is null or c.model is null or c.model = CAST(:vmodel AS text))
  and (CAST(:vyear AS int) is null or c.year_start is null
        or (c.year_start <= CAST(:vyear AS int)
            and (c.year_end is null or c.year_end >= CAST(:vyear AS int))))
"""

_SELECT_EVIDENCE = """
  select c.id as chunk_id, c.document_version_id, c.chunk_index, c.chunk_type,
         c.title as chunk_title, c.section_title, c.heading_path, c.page_start, c.page_end,
         c.content_plain as content, c.scope as scope_tier,
         c.make as chunk_make, c.model as chunk_model,
         c.year_start, c.year_end,
         v.version as document_version, v.source_filename, v.page_count as version_page_count,
         d.id as document_id, d.title as document_title, d.manufacturer,
         d.make as document_make, d.model as document_model,
         d.model_year_start, d.model_year_end, d.document_type
"""


def _row_to_evidence(
    row: Any, *, dense: float = 0.0, lexical: float = 0.0, hybrid: float = 0.0
) -> RetrievedEvidence:
    heading_path = row.heading_path
    if isinstance(heading_path, str):
        try:
            heading_path = json.loads(heading_path)
        except Exception:  # noqa: BLE001 - tolerate malformed json columns
            heading_path = []
    return RetrievedEvidence(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_version_id=row.document_version_id,
        document_version=row.document_version,
        title=row.document_title or row.chunk_title or "",
        manufacturer=row.manufacturer,
        make=row.document_make or row.chunk_make,
        model=row.document_model or row.chunk_model,
        model_year_start=row.model_year_start,
        model_year_end=row.model_year_end,
        document_type=row.document_type,
        source_filename=row.source_filename,
        section_title=row.section_title,
        heading_path=heading_path or [],
        page_start=row.page_start,
        page_end=row.page_end,
        content=row.content,
        scope=row.scope_tier,
        dense_score=dense,
        lexical_score=lexical,
        hybrid_score=hybrid,
    )


class RagRepository:
    """pgvector-backed corpus access for Phase 5 ingestion + retrieval.

    Constructed with an open ``AsyncConnection`` — raw SQL runs on that same
    connection, so callers can wrap ingestion in a transaction without
    re-connecting.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn
        self._probed: bool | None = None

    # ------------------------------------------------------------------ gates

    async def _ensure_vector(self) -> None:
        if self._probed is not None:
            return
        self._probed = False
        try:
            res = await self._conn.execute(
                sa.text("select 1 from pg_catalog.pg_extension where extname = 'vector'")
            )
            self._probed = bool(res.scalar())
        except Exception:  # noqa: BLE001
            self._probed = False
        if not self._probed:
            raise RAGVectorUnavailableError(
                "pgvector extension 'vector' is not installed in this database"
            )

    @staticmethod
    def _scope_params(scope: VehicleScope | None) -> dict[str, Any]:
        if not scope:
            return {}
        return {
            "vmake": scope.make,
            "vmodel": scope.model,
            "vyear": scope.year,
        }

    @staticmethod
    def _hybrid_order(_alpha: float) -> str:
        return "order by (:a * dense + :sh * lexical) desc"

    # ---------------------------------------------------------------- health

    async def health(self) -> dict[str, Any]:
        """Safe-to-call diagnostics (never searches)."""
        out: dict[str, Any] = {"pgvector_available": False, "corpus": {}}
        try:
            await self._ensure_vector()
            out["pgvector_available"] = True
            res = await self._conn.execute(
                sa.text(
                    "select (select count(*) from rag_documents), "
                    "(select count(*) from rag_document_versions), "
                    "(select count(*) from rag_chunks c "
                    "  join rag_document_versions v on v.id = c.document_version_id "
                    "  where v.ingestion_status = 'completed')"
                )
            )
            docs, versions, chunks = res.one()
            out["corpus"] = {
                "documents": docs,
                "versions": versions,
                "completed_chunks": chunks,
            }
        except RAGVectorUnavailableError:
            out["pgvector_available"] = False
        return out

    # ------------------------------------------------------------ identity

    async def get_document(self, canonical_source: str) -> dict[str, Any] | None:
        """Return the identity row for ``canonical_source`` or ``None``."""
        res = await self._conn.execute(
            sa.text(
                "select id, canonical_source, source_uri, title, manufacturer, "
                "make, model, model_year_start, model_year_end, document_type, "
                "language from rag_documents where canonical_source = :c"
            ),
            {"c": canonical_source},
        )
        row = res.mappings().first()
        return dict(row) if row else None

    async def latest_version(self, doc_id: uuid.UUID) -> dict[str, Any] | None:
        """Return the highest ``version`` row for ``doc_id`` or ``None``."""
        res = await self._conn.execute(
            sa.text(
                "select id, version, content_hash, ingestion_status, error_message "
                "from rag_document_versions where document_id = :d "
                "order by version desc limit 1"
            ),
            {"d": doc_id},
        )
        row = res.mappings().first()
        return dict(row) if row else None

    # ------------------------------------------------------------ ingestion

    async def upsert_document(
        self,
        doc_id: uuid.UUID,
        canonical_source: str,
        *,
        title: str,
        source_uri: str | None = None,
        source_type: str = "manufacturer",
        manufacturer: str | None = None,
        make: str | None = None,
        model: str | None = None,
        year_start: int | None = None,
        year_end: int | None = None,
        document_type: str = "service-manual",
        language: str | None = None,
    ) -> uuid.UUID:
        """Insert the document identity row, idempotent on ``canonical_source``."""
        res = await self._conn.execute(
            sa.text(
                "insert into rag_documents "
                "(id, canonical_source, source_uri, source_type, manufacturer, "
                " make, model, model_year_start, model_year_end, document_type, "
                " title, language) "
                "values (:id, :canon, :uri, :stype, :mfgr, :make, :model, :ys, :ye, "
                "        :dtype, :title, :lang) "
                "on conflict (canonical_source) do update set "
                " source_uri = excluded.source_uri, source_type = excluded.source_type, "
                " manufacturer = excluded.manufacturer, make = excluded.make, "
                " model = excluded.model, model_year_start = excluded.model_year_start, "
                " model_year_end = excluded.model_year_end, "
                " document_type = excluded.document_type, title = excluded.title, "
                " language = excluded.language "
                "returning id"
            ),
            {
                "id": doc_id,
                "canon": canonical_source,
                "uri": source_uri,
                "stype": source_type,
                "mfgr": manufacturer,
                "make": make,
                "model": model,
                "ys": year_start,
                "ye": year_end,
                "dtype": document_type,
                "title": title,
                "lang": language,
            },
        )
        return res.scalar_one()

    async def insert_version(
        self,
        version_id: uuid.UUID,
        doc_id: uuid.UUID,
        *,
        version: int,
        content_hash: str,
        source_filename: str,
        parser_name: str,
        parser_version: str | None,
        language: str | None,
        page_count: int | None,
        embedding_model: str,
        embedding_dimension: int,
        chunking_version: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert one *pending* immutable version (completed after chunks land)."""
        await self._conn.execute(
            sa.text(
                "insert into rag_document_versions "
                "(id, document_id, version, content_hash, source_filename, parser_name, "
                " parser_version, language, page_count, embedding_model, "
                " embedding_dimension, chunking_version, ingestion_status, metadata) "
                "values (:id, :doc, :ver, :hash, :src, :parser, :pver, :lang, :pages, "
                "        :emodel, :edim, :chunkver, 'pending', :meta)"
            ),
            {
                "id": version_id,
                "doc": doc_id,
                "ver": version,
                "hash": content_hash,
                "src": source_filename,
                "parser": parser_name,
                "pver": parser_version,
                "lang": language,
                "pages": page_count,
                "emodel": embedding_model,
                "edim": embedding_dimension,
                "chunkver": chunking_version,
                "meta": json.dumps(metadata or {}),
            },
        )

    async def complete_version(self, version_id: uuid.UUID) -> None:
        """Atomically mark a version ``completed`` (retrieval only reads these)."""
        await self._conn.execute(
            sa.text(
                "update rag_document_versions set ingestion_status = 'completed', "
                "error_message = null where id = :id"
            ),
            {"id": version_id},
        )

    async def fail_version(self, version_id: uuid.UUID, message: str) -> None:
        """Mark a version ``failed`` with the error that stopped ingestion."""
        await self._conn.execute(
            sa.text(
                "update rag_document_versions set ingestion_status = 'failed', "
                "error_message = :msg where id = :id"
            ),
            {"id": version_id, "msg": message[:2000]},
        )

    async def delete_chunks_for_version(self, version_id: uuid.UUID) -> int:
        """Remove orphaned chunks of a pending/failed version (idempotent)."""
        res = await self._conn.execute(
            sa.text("delete from rag_chunks where document_version_id = :id"),
            {"id": version_id},
        )
        return res.rowcount

    async def insert_chunk(self, row: ChunkRow, embedding: Sequence[float]) -> None:
        """Insert one vectorised chunk; ``embedding`` is a float sequence."""
        scope = VehicleScope(make=row.scope_make, model=row.scope_model, year=row.scope_year)
        tier = (
            derive_tier(scope)
            if (row.scope_make or row.scope_model or row.scope_year)
            else "GENERIC"
        )
        await self._conn.execute(
            sa.text(
                "insert into rag_chunks "
                "(id, document_version_id, chunk_index, chunk_type, title, section_title, "
                " heading_path, page_start, page_end, content_plain, content_tsv, "
                " scope, make, model, year_start, year_end, start_char, end_char, "
                " embedding_store) "
                "values (:id, :ver, :idx, :ctype, :title, :sec, :path, :ps, :pe, :content, "
                "        to_tsvector('english', :content), :scope, :make, :model, :ys, :ye, "
                "        :sc, :ec, :vec)"
            ),
            {
                "id": row.chunk_id,
                "ver": row.document_version_id,
                "idx": row.chunk_index,
                "ctype": row.chunk_type,
                "title": row.title,
                "sec": row.section_title,
                "path": json.dumps(row.heading_path),
                "ps": row.page_start,
                "pe": row.page_end,
                "content": row.content,
                "scope": tier,
                "make": row.scope_make,
                "model": row.scope_model,
                "ys": row.scope_year,
                "ye": row.scope_year,
                "sc": row.start_char,
                "ec": row.end_char,
                "vec": vector_literal(embedding),
            },
        )

    # ---------------------------------------------------------- document admin

    async def list_documents(
        self,
        *,
        limit: int,
        offset: int,
        make: str | None = None,
        model: str | None = None,
        year: int | None = None,
        canonical: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginated corpus documents with version counts, newest first.

        Filters are exact matches on the document identity columns; ``year``
        matches documents whose model-year range contains the value; ``status``
        matches documents that have at least one version in that state. Returns
        ``(item_rows, total)``.
        """
        await self._ensure_vector()
        where: list[str] = []
        params: dict[str, Any] = {}
        if canonical:
            where.append("d.canonical_source = :canon")
            params["canon"] = canonical
        if make:
            where.append("d.make = :mk")
            params["mk"] = make
        if model:
            where.append("d.model = :md")
            params["md"] = model
        if year is not None:
            where.append(
                "(d.model_year_start is null or "
                "(d.model_year_start <= :yr and "
                "(d.model_year_end is null or d.model_year_end >= :yr)))"
            )
            params["yr"] = year
        if status:
            where.append(
                "exists (select 1 from rag_document_versions v "
                "where v.document_id = d.id and v.ingestion_status = :st)"
            )
            params["st"] = status
        where_sql = f" where {' and '.join(where)}" if where else ""

        total_res = await self._conn.execute(
            sa.text(f"select count(*) from rag_documents d{where_sql}"), params
        )
        total = int(total_res.scalar() or 0)

        select_sql = sa.text(
            "select d.id, d.source_type, d.canonical_source, d.source_uri, d.manufacturer, "
            "d.make, d.model, d.model_year_start, d.model_year_end, d.document_type, "
            "d.title, d.language, d.created_at, d.updated_at, "
            "(select count(*) from rag_document_versions v "
            " where v.document_id = d.id) as version_count, "
            "(select v.ingestion_status from rag_document_versions v "
            " where v.document_id = d.id order by v.version desc limit 1) as latest_status "
            f"from rag_documents d{where_sql} "
            "order by d.updated_at desc, d.id limit :lim offset :off"
        )
        res = await self._conn.execute(select_sql, {**params, "lim": limit, "off": offset})
        rows = res.mappings().all()
        return [dict(r) for r in rows], total

    async def get_document_detail(self, document_id: uuid.UUID) -> dict[str, Any] | None:
        """Return ``{"document": row, "versions": [rows with chunk_count]}`` or None."""
        await self._ensure_vector()
        res = await self._conn.execute(
            sa.text("select * from rag_documents where id = :id"), {"id": document_id}
        )
        row = res.mappings().first()
        if row is None:
            return None
        versions_res = await self._conn.execute(
            sa.text(
                "select v.*, "
                "(select count(*) from rag_chunks c "
                " where c.document_version_id = v.id) as chunk_count "
                "from rag_document_versions v where v.document_id = :id order by v.version"
            ),
            {"id": document_id},
        )
        return {
            "document": dict(row),
            "versions": [dict(r) for r in versions_res.mappings().all()],
        }

    async def delete_document(self, document_id: uuid.UUID) -> bool:
        """Cascade-delete a document and its versions/chunks (transactional).

        The Phase 5 FKs are *not* ``ON DELETE CASCADE`` (only the ORM
        relationships cascade), so dependent rows are removed explicitly in
        child-first order within the caller's connection transaction. Return
        ``False`` when no such document exists.
        """
        await self._ensure_vector()
        exists = await self._conn.execute(
            sa.text("select 1 from rag_documents where id = :id"), {"id": document_id}
        )
        if exists.scalar() is None:
            return False
        await self._conn.execute(
            sa.text(
                "delete from rag_chunks c using rag_document_versions v "
                "where c.document_version_id = v.id and v.document_id = :id"
            ),
            {"id": document_id},
        )
        await self._conn.execute(
            sa.text("delete from rag_document_versions where document_id = :id"),
            {"id": document_id},
        )
        await self._conn.execute(
            sa.text("delete from rag_documents where id = :id"), {"id": document_id}
        )
        return True

    # ------------------------------------------------------------- retrieval

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        top_k: int = 5,
        vehicle_scope: VehicleScope | None = None,
    ) -> list[RetrievedEvidence]:
        """Dense (``<=>``) + lexical (``ts_rank_cd``) hybrid search, scope-filtered."""
        return await self._search(
            query_text, query_embedding, top_k=top_k, vehicle_scope=vehicle_scope, mode="hybrid"
        )

    async def dense_search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        top_k: int = 5,
        vehicle_scope: VehicleScope | None = None,
    ) -> list[RetrievedEvidence]:
        """Pure cosine-distance retrieval leg, scope-filtered."""
        return await self._search(
            query_text, query_embedding, top_k=top_k, vehicle_scope=vehicle_scope, mode="dense"
        )

    async def lexical_search(
        self, query_text: str, *, top_k: int = 5, vehicle_scope: VehicleScope | None = None
    ) -> list[RetrievedEvidence]:
        """Pure FTS ``ts_rank_cd`` retrieval leg, scope-filtered."""
        await self._ensure_vector()
        params = {"q": query_text, "k": top_k}
        params.update(self._scope_params(vehicle_scope))
        sql = sa.text(
            f"with scored as ("
            f" {_SELECT_EVIDENCE}, "
            f"  ts_rank_cd(c.content_tsv, plainto_tsquery('english', :q)) as lexical "
            f"  from rag_chunks c "
            f"  join rag_document_versions v on v.id = c.document_version_id "
            f"  join rag_documents d on d.id = v.document_id "
            f"  where v.ingestion_status = 'completed' and {_SCOPE_FILTER}"
            f") "
            f"select * from scored where lexical > 0 order by lexical desc limit :k"
        )
        rows = await self._conn.execute(sql, params)
        out: list[RetrievedEvidence] = []
        for r in rows:
            out.append(_row_to_evidence(r, lexical=float(r.lexical)))
        return out

    async def _search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        vehicle_scope: VehicleScope | None,
        mode: str,
    ) -> list[RetrievedEvidence]:
        await self._ensure_vector()
        settings = get_rag_settings()
        alpha = settings.rag_hybrid_alpha
        params: dict[str, Any] = {
            "q": query_text,
            "k": top_k,
            "v": vector_literal(query_embedding),
            "a": alpha,
            "sh": 1.0 - alpha,
        }
        params.update(self._scope_params(vehicle_scope))

        if mode == "dense":
            order_col = "dense"
            extra = "  (1.0 - (c.embedding_store <=> :v)) as dense"
            order = f"order by {order_col} desc"
        elif mode == "lexical":
            order_col = "lexical"
            extra = "  ts_rank_cd(c.content_tsv, plainto_tsquery('english', :q)) as lexical"
            order = f"order by {order_col} desc"
        else:  # hybrid
            order = self._hybrid_order(alpha)
            extra = (
                "  (1.0 - (c.embedding_store <=> :v)) as dense, "
                "  ts_rank_cd(c.content_tsv, plainto_tsquery('english', :q)) as lexical, "
                "  (:a * (1.0 - (c.embedding_store <=> :v)) + "
                "   :sh * ts_rank_cd(c.content_tsv, plainto_tsquery('english', :q))) as hybrid"
            )

        sql = sa.text(
            f"with scored as ("
            f" {_SELECT_EVIDENCE}, {extra} "
            f"  from rag_chunks c "
            f"  join rag_document_versions v on v.id = c.document_version_id "
            f"  join rag_documents d on d.id = v.document_id "
            f"  where v.ingestion_status = 'completed' and {_SCOPE_FILTER}"
            f") "
            f"select * from scored"
            f" {' where dense is not null' if mode in ('dense', 'hybrid') else ''} "
            f"{order} limit :k"
        )
        rows = await self._conn.execute(sql, params)
        out: list[RetrievedEvidence] = []
        for r in rows:
            out.append(
                _row_to_evidence(
                    r,
                    dense=float(r.dense) if hasattr(r, "dense") else 0.0,
                    lexical=float(r.lexical) if hasattr(r, "lexical") else 0.0,
                    hybrid=float(r.hybrid) if hasattr(r, "hybrid") else 0.0,
                )
            )
        return out
