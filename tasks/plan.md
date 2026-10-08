# Implementation Plan: Completing the Digital Twin Platform

Status: AUDIT COMPLETE — proceeding to implementation.
Baseline verified on `main` @ `3d1aca2` + 5 uncommitted P0 fixes.

## 1. Capability Map

| Module id | Responsibility | Depends on |
|---|---|---|
| `automation` | Health evaluation + critical-event diagnosis run without a human clicking a button | telemetry, health, agent |
| `security` | Password byte-length correctness, password change, auth rate limiting | auth |
| `realtime` | Live telemetry transport (SSE) and stale/live UX states | telemetry |
| `devtooling` | CI, migration test, cross-platform Makefile, hermetic test env | — |
| `polish` | Metadata/docs accuracy, Swagger extension gap, graph compile cache, cookie path | — |

Build order: `automation` → `security` → `realtime` → `devtooling` → `polish`

Rationale: `automation` is the difference between "a real platform" and "disconnected
demos" — telemetry flows continuously today but nothing ever evaluates it unless a human
presses Analyze. `security` closes a known correctness bug and two hardening gaps.
`realtime` removes polling. `devtooling` locks the gains in. `polish` is cheap accuracy.

## 2. System Audit Matrix

| # | Subsystem | Status |
|---|---|---|
| 1 | Project foundation | IMPLEMENTED |
| 2 | Configuration | PARTIAL (`.env.example` omits RAG keys) |
| 3 | PostgreSQL | IMPLEMENTED (Supabase, live at head) |
| 4 | SQLAlchemy | IMPLEMENTED |
| 5 | Alembic | IMPLEMENTED (7 revisions, single head `d6a9b1c2e3f4`) |
| 6 | Vehicle management | IMPLEMENTED |
| 7 | Telemetry ingestion | IMPLEMENTED |
| 8 | MQTT | IMPLEMENTED (sequential, no DLQ) |
| 9 | Vehicle simulator | IMPLEMENTED (4 scenarios, seeded, monotonic fuel/odometer) |
| 10 | Telemetry persistence | IMPLEMENTED (partial unique index, idempotent) |
| 11 | Vehicle context engine | IMPLEMENTED |
| 12 | Statistical analysis | IMPLEMENTED |
| 13 | Trend analysis | IMPLEMENTED |
| 14 | Rule/anomaly detection | IMPLEMENTED |
| 15 | Vehicle health scoring | IMPLEMENTED (penalties 0/10/30, category cap 40) |
| 16 | Health snapshots | IMPLEMENTED (immutable, schema-versioned) |
| 17 | Health history | IMPLEMENTED |
| 18 | LangGraph | IMPLEMENTED |
| 19 | Supervisor agent | IMPLEMENTED |
| 20 | Tool architecture | IMPLEMENTED (deterministic, no LLM SQL) |
| 21 | LLM provider abstraction | IMPLEMENTED (OpenRouter/Groq/Mock) |
| 22 | LLM fallback | IMPLEMENTED (correct eligibility filtering) |
| 23 | Manufacturer documentation ingestion | IMPLEMENTED |
| 24 | Document parsing | IMPLEMENTED (17 extensions) |
| 25 | Chunking | IMPLEMENTED (structural-1.0.0, 800/120) |
| 26 | Embeddings | IMPLEMENTED (bge-m3, 1024) |
| 27 | pgvector | IMPLEMENTED (P0 fixed, unverified in Docker) |
| 28 | Hybrid retrieval | IMPLEMENTED (alpha 0.6, 25/30/5) |
| 29 | Reranking | IMPLEMENTED (bge-reranker-v2-m3, graceful degradation) |
| 30 | RAG scope filtering | IMPLEMENTED |
| 31 | Citation/evidence handling | IMPLEMENTED |
| 32 | RAG security/prompt-injection isolation | IMPLEMENTED |
| 33 | Diagnosis generation | IMPLEMENTED |
| 34 | Recommendation generation | IMPLEMENTED |
| 35 | Authentication | IMPLEMENTED |
| 36 | JWT/access tokens | IMPLEMENTED |
| 37 | Refresh-token rotation | IMPLEMENTED (family revocation) |
| 38 | Password security | **BROKEN** (72 chars vs 72 bytes; no change endpoint) |
| 39 | User management | PARTIAL (no password change) |
| 40 | Vehicle ownership | IMPLEMENTED |
| 41 | Authorization/IDOR protection | IMPLEMENTED |
| 42 | API contracts | IMPLEMENTED (23 paths / 30 ops) |
| 43 | Error handling | IMPLEMENTED (21 handlers) |
| 44 | Logging | IMPLEMENTED |
| 45 | Security | **PARTIAL** (no rate limiting) |
| 46 | Tests | IMPLEMENTED (381 pass / 10 skip) |
| 47 | Docker | PARTIAL (P0 fixed, daemon unavailable) |
| 48 | CI / developer tooling | **MISSING** (no `.github`); Makefile Windows-broken |
| 49 | Frontend | IMPLEMENTED (13 routes, 69 tests) |
| 50 | Dashboard | IMPLEMENTED |
| 51 | Vehicle detail view | IMPLEMENTED (5 tabs) |
| 52 | Live telemetry | **PARTIAL** (polling only, no live transport) |
| 53 | Health visualization | IMPLEMENTED |
| 54 | Diagnostic interface | IMPLEMENTED |
| 55 | RAG evidence/citations UI | IMPLEMENTED |
| 56 | Reports | **MISSING** (no endpoint, no page) |
| 57 | Documentation | PARTIAL (stale Phase 1 metadata, stale README) |

Cross-cutting gaps not in the numbered list:

- **Automatic health evaluation after telemetry ingestion** — MISSING. `TelemetryService.create_telemetry` persists only. Nothing calls `VehicleHealthService.analyze_vehicle` outside an explicit HTTP request.
- **Automatic critical-event agent trigger** — MISSING. `AgentService.run_critical_event` exists with cooldown deduplication but has no caller.

## 3. Gap Analysis

### Module: automation (P1)

- **Current state:** simulator publishes every second; MQTT persists every record; health snapshots are only created when a human POSTs `/health/analyze`. Agent critical-event endpoint exists but has no caller.
- **Expected behavior:** the platform evaluates health on its own as telemetry arrives, and escalates to the diagnostic agent when an evaluation is critical.
- **Missing:** a scheduler that selects vehicles with telemetry newer than their latest snapshot, runs `VehicleHealthService.analyze_vehicle`, and triggers `AgentService.run_critical_event` on critical/invalid states.
- **Affected files:** new `app/services/health_monitor.py`, `app/core/config.py` (knobs), `app/main.py` (lifespan), new repository query.
- **Dependencies:** existing `VehicleHealthService`, `AgentService`, `HealthSnapshotRepository`.
- **Tests required:** selection/throttle logic, critical escalation, disabled mode, no-op when up to date.
- **Risks:** unbounded work, blocking the event loop, running against a vehicle with no telemetry, LLM cost from repeated triggers (mitigated by existing cooldown).
- **Order:** first.

### Module: security (P1)

- **Current state:** `max_length=72` on *characters*; bcrypt enforces 72 *bytes*. Registration returns 500 for 37-72 char non-ASCII passwords; those accounts can never log in. No password change endpoint. No rate limiting.
- **Expected behavior:** consistent byte-length contract; users can change their own password; auth endpoints are metered.
- **Affected files:** `app/schemas/auth.py`, `app/core/security.py`, `app/services/auth_service.py`, `app/api/routes/auth.py`, `app/main.py`.
- **Tests required:** 72-byte ASCII boundary, non-ASCII rejection as 422, change-password success/incorrect-current, rate-limit responses.
- **Order:** second.

### Module: realtime (P2)

- **Current state:** frontend polls `/vehicles/{id}/telemetry` on a timer. No WebSocket/SSE anywhere in the backend.
- **Expected behavior:** live telemetry with connection state, last-received timestamp, stale detection; no fake frontend timers generating data.
- **Affected files:** new `app/api/routes/live.py`, `app/api/router.py`, frontend hook/component.
- **Risks:** per-connection DB load; must stay behind the existing session/auth dependency.
- **Order:** third.

### Module: devtooling (P2)

- **Current state:** no `.github/`; Makefile hardcodes `.venv/bin/` which does not exist on Windows; tests rely on ambient `AUTH_ACCESS_TOKEN_MINUTES`.
- **Expected behavior:** CI runs lint/typecheck/tests plus a real `alembic upgrade head` against pgvector; `make test` works on Windows.
- **Affected files:** new `.github/workflows/ci.yml`, `backend/Makefile`, `tests/conftest.py`.
- **Order:** fourth.

### Module: polish (P3)

- Stale `description` in `main.py` ("Phase 1"); stale `backend/README.md` registration contract; `.env.example` missing `RAG_*`; Swagger upload help missing `.odt/.ods/.odp/.epub`; per-request LangGraph compile; frontend dead `/api/session/logout` string and cookie path mismatch.
- **Order:** fifth.

### Not implemented (explicitly out of scope)

**Reports.** No report endpoint or page exists, and reports are not in the required frontend IA (items 1-17). The brief makes reports conditional ("if report generation is part of the intended final system"). Rather than invent an unrequested surface, this is recorded as remaining debt. Say so honestly in the final report.

## 4. Task List

See `tasks/todo.md`.

## 5. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Automation triggers LLM spend on every critical evaluation | High | Reuse existing `agent_critical_event_cooldown_seconds` dedup; run agent only on `critical`/invalid status |
| Background loop leaks or blocks shutdown | Medium | Keep task handle, cancel in lifespan teardown, catch per-vehicle exceptions |
| Rate limiter breaks test suite | Medium | Disable by default in `test` env; opt-in knob |
| SSE endpoint bypasses auth | High | Reuse `get_current_user` dependency; ownership check before streaming |
| New tests hit live Supabase | Critical | Existing conftest guard already refuses hosts containing `supabase`/`pooler` |
| Regression against 381-test baseline | High | Run full suite after every module; never weaken a test |

## 6. Open Questions Resolved

- **Q: Is reports in scope?** A: No — not required by the acceptance flow or the IA list; recorded as debt.
- **Q: Should automation call the LLM every tick?** A: No — cooldown is already implemented in `AgentService._deduplicated_prior`.
