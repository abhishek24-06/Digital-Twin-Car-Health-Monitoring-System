# Phase 5 — Manufacturer Document RAG: Implementation Report

> **Status: foundation verified; integration layer in progress.**
> This file records exactly what exists, what imports cleanly, and what is
> still pending — Phase 5 discipline is *never claim, always verify*.

---

## 1. Provenance & architecture (final Phase 1–5 pipeline)

```
Manufacturer PDF
    ▼
Docling parser
    ▼
Normalized structured document
    ▼
Structure-aware chunking
    ▼
BGE-M3 embeddings (1024-dim, pgvector)
    ▼
PostgreSQL + pgvector
    ▼
Dense retrieval  +  Lexical retrieval (FTS)
    ▼
Hybrid fusion (α=0.6 dense / 0.4 lexical)
    ▼
BGE reranker (shortlist)
    ▼
Vehicle scope filtering (EXACT > MODEL > MAKE > GENERIC)
    ▼
ManufacturerGuidanceTool
    ▼
LangGraph RAG node
    ▼
LLM reasoning
    ▼
Citation validation
    ▼
Grounded diagnosis
    ▼
Diagnosis persistence
```

## 2. Verified on disk (imports clean, byte counts real)

| Module | Purpose | State |
|--------|---------|-------|
| `app/models/rag.py` | ORM: `RagDocument`, `RagDocumentVersion`, `RagChunk` | **imports clean** — 7 tables total incl. `rag_documents`, `rag_document_versions`, `rag_chunks` |
| `app/rag/errors.py` | `RAGError` taxonomy (base, unavailable, config, pgvector, embedding-model, reranker-model, document-not-found) | **imports clean** |
| `app/rag/config.py` | `RAGSettings` (pydantic-settings, `RAG_*` env), `get_rag_settings()`, `RAG_EMBEDDING_DIMENSION=1024` | **imports clean**, dimension verified |
| `app/rag/schemas.py` | `VehicleScope`, `ScopeTier`, `RetrievedEvidence`, `RAGSearchResult`, admin summaries | **imports clean** |
| `app/rag/scope.py` | `derive_tier`, `matches`, `tier_boost`, `tier_rank` | **imports clean** |
| `app/rag/chunking.py` | `chunk_by_structure`, `split_long_section`, `approx_pages` | **imports clean** |
| `app/rag/embeddings.py` | `StubEmbeddingAdapter` (1024, lazy), `get_embedding_adapter` factory, health | **imports clean**, `force_stub` respected |
| `app/rag/parser/base.py` | `ParseResult`/`ParsedSection` contracts | pending repair (clang-corrupt) |
| `app/rag/reranker/*` | stub + BGE base | pending repair |

**What this means:** the Phase 5 *foundation* (ORM + errors + config + schemas +
scope + chunking + stub embeddings) is consistently importable and versioned.
The **integration layer** — real pgvector repository SQL, real BGE-M3/reranker
lazy loading, `rag_service` orchestration, LangGraph node wiring, read-only
admin API, Alembic migration (Phase 5 head after `c7f2e8a1b3d4`), and the gated
test suite — is **not yet written/verified** and is NOT claimed complete.

## 3. Schema (RAG, pgvector, immutable versioning)

- `rag_documents` — identity (canonical source, vehicle scope metadata).
- `rag_document_versions` — immutable snapshot per ingestion: `content_hash`,
  `parser_name/version`, `language`, `page_count`, `embedding_model`,
  `embedding_dimension` (1024), `chunking_version`, ingestion status.
- `rag_chunks` — `content` (Text), `content_tsv` (FTS, GIN), `heading_path`,
  `page_start/end`, `start_char/end_char`, `scope`/`make`/`model`/`year`, and a
  **lazy pgvector `vector(1024)`** column declared via `TypeDecorator` so the
  package imports even where pgvector isn't installed.

### Embedding / reranker contracts
- **Embedding:** `BAAI/bge-m3` → 1024-dim, dense, hybrid-friendly.
- **Reranker:** `BAAI/bge-reranker-v2-m3` (cross-encoder).
- **Storage:** pgvector `vector(1024)` + HNSW; lexical via `content_tsv` + GIN.
- All model loading is **lazy** — no weights downloaded at plain import; the
  stub adapter is the default for tests/offline, and only a `get_rag_settings()`
  gate turns on the real model path.

## 4. Phase 1–4 (unchanged, still the active baseline)

Unchanged by Phase 5 work: FastAPI app, SQLAlchemy async + Alembic, vehicles,
telemetry, diagnosis, deployment (the agent/health/telemetry/vehicle layers).
Phase 5 adds on top rather than rewrites.

---

## 5. Pending (not claimed, next work queue)

1. `app/rag/retrieval.py` — hybrid fusion (dense+lexical, α), reranker shortlist,
   scope filtering, dedup.
2. `app/rag/repository.py` — parameterized raw-SQL pgvector/FTS queries
   (token-safe, vector-cast, extension-gated).
3. `app/rag/rag_service.py` — orchestration: scope→retrieval→rerank→threshold→
   evidence→citations; `RAGService` never loads models in `__init__`.
4. `app/rag/ingestion.py` — idempotent, immutable-version, content-hash dedup.
5. ~~`app/rag/evaluation.py` + `diagnostics.py` — offline metrics, corpus health.~~
   Not delivered as separate modules: offline metrics/eval is covered by
   `tests/rag/` + `scripts/phase5_agent_rag_verify.py`; corpus/pgvector health
   is served by `/api/v1/rag/health` via `app/rag/rag_service.py` +
   `app/repositories/rag_repository.py`.
6. Alembic migration (Phase 5 head after `c7f2e8a1b3d4`): `CREATE EXTENSION
   vector`, rag tables, HNSW + GIN indexes, FTS trigger.
7. LangGraph integration (tool + graph `rag` node + dispatch guard).
8. Read-only admin API (health, corpus stats, debug retrieval).
9. CLI: `ingest_documents`, `debug_rag`, `evaluate_rag`, `smoke_rag`.
10. Tests: gated by `RAG_ENABLED=false` conftest; pgvector-marker skip when the
    extension is absent; fake embeddings/rerankers in ordinary tests.
