# Phase 5 RAG — Implementation Status & Remaining Work (truthful)

_Last verified: this session, green smoke run output captured below._

## What is REAL and green on disk

All of this was imported and exercised in the venv, not just compiled:

- `app/models/rag.py` — `RagDocument`, `RagDocumentVersion`, `RagChunk`
  (pgvector lazy `TypeDecorator`, immutable versioning, content hash,
  FTS `content_tsv` + GIN, provenance/scope/char+page columns). Imports
  cleanly and registers rag tables with `app.models`.
- `app/rag/errors.py` — full taxonomy (`RAGError` → `RAGUnavailableError`,
  `RAGDisabledError`, `RAGConfigurationError`, `RAGDocumentNotFoundError`,
  model-unavailable types, `RAGVectorUnavailableError`).
- `app/rag/config.py` — `RAGSettings` (env-driven, `RAG_EMBEDDING_DIMENSION`), 
  `get_rag_settings()`.
- `app/rag/schemas.py` — `VehicleScope`, `ScopeTier`, `RetrievedEvidence`,
  `RAGSearchResult`, `RAGHealthResponse`, admin summaries.
- `app/rag/scope.py` — tier derivation/rank/matching/boost.
- `app/rag/chunking.py` — structure-aware chunking (headings, scopes, pages,
  headings), deterministic.
- `app/rag/embeddings.py` — `StubEmbeddingAdapter` (1024-dim, deterministic)
  + `get_embedding_adapter` factory (real BGE-M3 behind lazy gate).
- `app/rag/query_builder.py` — `VehicleScope`-aware plan builder.
- `app/rag/parser/{__init__,base,plain_text}.py` + `parser/` base contracts.
- `app/rag/reranker/base.py` — stub reranker (monotone, deterministic).

### Green smoke output (captured this session)

```
[ok]  scope EXACT tier             EXACT_VEHICLE
[ok]  scope MAKE tier              MAKE
[ok]  rank EXACT                   3
[ok]  rank MAKE                    1
[ok]  boost MODEL                  0.25
[ok]  boost MAKE                   0.1
[ok]  promote MODEL                 True
[ok]  drop wrong-make              False
[ok]  drop wrong-year              False
[ok]  chunk count                  19
[ok]  chunk types                  ['continuation', 'section']
[ok]  chunk0 title                 Brakes
[ok]  chunk0 pages                 1-1
[ok]  chunk0 path                  Brakes
[ok]  stub dim                     1024
[ok]  stub encode                  [1, 1024]
[ok]  stub health                  ['adapter', 'dimension']
[ok]  model table count            7
[ok]  rag tables                   ['rag_chunks', 'rag_document_versions', 'rag_documents']
```

## NOT yet done (requires pgvector/pg in local env — never faked)

- `app/rag/repository.py` — real raw-SQL pgvector/FTS repository (authored,
  needs live pgvector + `CREATE EXTENSION vector` gating).
- `app/rag/rag_service.py`, `ingestion.py` — orchestration, idempotent ingestion;
  corpus health served by `app/repositories/rag_repository.py` + `/api/v1/rag/health`
  (there is no separate `evaluation.py` / `diagnostics.py` module).
- Alembic migration (Phase 5 head after `c7f2e8a1b3d4`) — `rag_documents`,
  `rag_document_versions`, `rag_chunks`, pgvector HNSW + GIN indexes, FTS
  trigger.
- Agent wiring: `tool.py` (ManufacturerGuidanceTool via RAGService) + LangGraph
  `rag` node + dispatch guard.
- Read-only admin API (health/stats/debug-retrieval), CLI scripts
  (ingest/docs/eval/smoke/debug), `scripts/` drivers.
- Tests gated behind `RAG_ENABLED=false` (never download BGE-M3 locally),
  conftest pgvector awareness, `tests/rag/` suite.

## Next step (unblocking order)

1. `repository.py` raw-SQL repo against local pg + `CREATE EXTENSION vector`
   (Supabase path does already have pgvector).
2. Alembic migration + `alembic upgrade head` on local/Supabase.
3. `rag_service.py` + ingestion + corpus-health endpoint (`/api/v1/rag/health`).
4. Migrate corpus → chunk → embed (stub BGE-M3) → index → verify counts.
5. Agent + API + CLI wiring; then run the real smoke with an actual bge-m3
   load outside pytest.

No Phase 5 feature is marked complete that was not actually exercised.
