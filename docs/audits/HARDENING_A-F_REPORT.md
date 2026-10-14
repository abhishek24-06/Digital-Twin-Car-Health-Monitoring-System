# Hardening Phases A–F — Consolidated Report

**Date:** 2026-10-13 · **Branch:** `main` (all work uncommitted) · **Code revision:** `66674bd`
**Scope:** audit-ready status of hardening phases **A–F** defined in
`docs/IMPLEMENTATION_ROADMAP.md` (phases G–K are out of scope here and remain
not started).

> **Claim discipline.** Each phase is marked **verified**, **implemented**,
> **partially implemented**, or **not started**, matching what the working tree
> and executed tests actually show. Where a result was produced earlier and not
> re-run in this session, it is labelled *roadmap-recorded*. Nothing not
> re-verified here is upgraded to "verified".

| Phase | Item | Status | Verified this session |
| --- | --- | --- | --- |
| **A** | Analyze-endpoint abuse control (rate limit + coalescing) | ✅ implemented | code + unit/API tests pass |
| **B** | Deployment & migration verification | ✅ implemented | code present; tests in suite |
| **C** | Real MQTT integration acceptance | ✅ implemented + verified | **yes — 7 passed** |
| **D** | Real browser acceptance (all eight tabs) | ✅ implemented + verified | not re-run (needs Node/browsers) |
| **E** | Simulation lifecycle + multi-worker safety | 🟡 partially implemented; multi-worker unverified | code inspected |
| **F** | AI/RAG reliability + offline evaluation | 🟠 partially: grounding metric done, RAG offline eval not started | this session's RQ5 work |

---

## Phase A — Analyze-endpoint abuse control ✅ implemented

**Objective.** Bound abuse of `POST /api/v1/vehicles/{id}/health/analyze` without
weakening `GET /health/live` (read-only) or monitor persistence / current-run
isolation.

**In the tree (verified read-only).**

- `backend/app/core/config.py` — per-user limiter settings
  (`analysis_*`), single-worker model documented.
- `backend/app/core/rate_limit.py` — reusable per-key limiter.
- `backend/app/services/analysis_coordinator.py` — `AnalysisCoordinator`
  (line 33) coalesces only **identical concurrent** analyses (same caller,
  vehicle, `window_minutes`); sequential/distinct requests are never merged.
- `backend/app/api/routes/vehicle_health.py` — `_limit_analysis` dependency
  (line 50) enforced before the handler; analysis runs through the
  process-wide coordinator (line 36).
- `frontend/src/components/states/feedback.tsx` — 429 "Too many requests" preset.

**Tests.** `backend/tests/services/test_analysis_coordinator.py`,
`backend/tests/api/test_health_analyze_limits.py`, and the frontend
`feedback` tests. All are collected by the suites run below.

**Honest limitation.** The limiter and coordinator are **process-local**,
consistent with the documented single-worker deployment; behind multiple workers
each process would limit/coalesce its own callers only. A shared (Postgres/Redis)
limiter is the follow-up if multi-worker is ever required. This is a documented
limitation, not a silent fallback.

---

## Phase B — Deployment & migration verification ✅ implemented

**Objective.** Make deployment/schema drift *visible* without applying
migrations or exposing secrets.

**In the tree (verified read-only).**

- `backend/app/core/config.py` — `build_id` (default `"unknown"`) and
  `expected_schema_revision` (default `None`) (line 63).
- `backend/app/schemas/health.py` — `DeploymentStatusResponse` with
  `expected_schema_revision` (line 29) and `migration_in_sync` (line 33).
- `backend/app/services/deployment_status.py` — read-only helpers (never raises
  for an unmigrated DB; reads OpenAPI paths for feature detection).
- `backend/app/api/routes/health.py` — admin-only `GET /health/deployment`
  (lines 77–91) reporting revision drift; `/` and `/db` unchanged.
- `docs/DEPLOYMENT_AND_OPERATIONS.md` — build identity, verification endpoint,
  required-secret rules, reviewed-migration procedure with mandatory backup,
  single-worker model, backup/DR assumptions.

**Tests.** `backend/tests/api/test_deployment_status.py` (401 unauth, 403
non-admin, unconfigured expected revision, schema drift via a temporary
`alembic_version` row with cleanup).

**Honest caveats.** The **running backend on :8000 is stale** (pre-Phase-3; does
not expose `/alerts`) and the **hosted DB is not migrated** to head
`e5f6a7b8c9d0`. Neither was changed here: restarting the backend / migrating the
hosted DB is an operator action requiring a real `JWT_SECRET` and a backup.

---

## Phase C — Real MQTT integration acceptance ✅ implemented + verified

**Objective.** Prove the real ingestion path against a real broker and a
disposable database, fail-closed.

**In the tree.** `backend/tests/mqtt/conftest.py` (private Mosquitto on a free
loopback port, `persistence false`; disposable DB), 
`backend/tests/mqtt/test_mqtt_integration.py`, `mqtt_integration` marker in
`backend/pyproject.toml` (line 63), `backend/scripts/run_mqtt_integration.py`,
`make mqtt-integration`, `docs/mqtt-integration-testing.md`.

**Safety contract (fail-closed).** The suite **skips** unless
`DT_MQTT_TEST_DATABASE_URL` is set (conftest line 41/62); when set, the host must
be loopback and the database must be exactly `digital_twin_mqtt_test`; hosted
markers abort with `RuntimeError`.

**Executed this session (from `backend/`).**

| Command | Result |
| --- | --- |
| `python scripts/run_mqtt_integration.py -q` | **7 passed** (exit 0) |

The scenario set matches the RQ6 robustness work: publish/persistence, duplicate
`event_id`, malformed/unknown/unrelated topics, delayed + out-of-order
timestamps, broker restart, transient DB failure, retry exhaustion, run-id
isolation.

---

## Phase D — Real browser acceptance, all eight tabs ✅ implemented + verified

**Objective.** Drive the real Next.js app against an isolated real backend in a
browser.

**In the tree.** `frontend/playwright.config.ts`,
`backend/scripts/run_e2e_backend.py` (fail-closed launcher: loopback DB named
exactly `digital_twin_browser_test`, seeds owners/vehicles/telemetry, runs the
real engine, `LLM_*_PROVIDER=mock`, health monitor disabled, MQTT pointed at a
dead port, `DATABASE_URL` forced), `frontend/e2e/vehicle-acceptance.spec.ts`,
`frontend/e2e/support.ts`, `frontend/e2e/README.md`.

**Status.** **Implemented + verified** (recorded in the roadmap: `npx playwright
test` → **7 passed**). A real defect was found and fixed: the Analytics grid
forced a **+216 px** horizontal overflow at 375 px; grid cards gained `min-w-0`
and the phone-layout test now guards it.

**Not re-run in this session.** It requires Node + Playwright browsers and is
independent of the RQ1–RQ6 work; the roadmap recording is cited as-is rather
than re-asserted. **Not covered:** SSE reconnect after a mid-session drop,
provider-failure UI, and alert acknowledge/resolve mutations in the browser.

---

## Phase E — Simulation lifecycle + multi-worker safety 🟠 partially implemented

**Objective.** Safe simulation start/stop lifecycle and correctness under
multiple workers.

**Status.** Single-worker lifecycle is implemented; **multi-worker safety is
unverified**. The platform documents a single-worker deployment (and Phases A/B
carry the same process-local caveat). No multi-worker test or shared-state
mechanism (Postgres/Redis limiter, cross-worker coordinator) has been
implemented. This report does **not** claim multi-worker correctness.

**Recommendation.** Either make single-worker a hard, enforced deployment
constraint or implement shared-state coordination before horizontal scaling.

---

## Phase F — AI/RAG reliability + offline evaluation 🟠 partially implemented

**Objective.** Reliable AI/RAG behaviour with an offline evaluation harness.

**What exists now.**

- The diagnosis workflow and grounding/validation layer are implemented
  (`backend/app/agent/**`, RAG in `backend/app/rag/**`).
- The **grounding contract** metric and its tests exist
  (`backend/evaluation/metrics/diagnosis.py`), and this session's RQ5 review
  classifies diagnosis **correctness as NOT EVALUABLE** (no expert reference);
  only grounding is measurable.
- A deterministic `mock` LLM provider is used in tests; RAG is disabled there.

**What is missing (honest status).**

- **No offline RAG accuracy harness**: retrieval quality (precision/recall of
  retrieved guidance) is not measured.
- Local Postgres has **no pgvector**, so the RAG path may absorb a
  `retrieval-error`; retrieval reliability is therefore **not validated** here.

**Recommendation.** Add an offline retrieval-evaluation set (query → expected
guidance) and a pgvector-capable environment, then report retrieval metrics
separately from (still non-evaluable) diagnostic correctness.

---

## Verification executed this session (from `backend/`)

| Gate | Command | Result |
| --- | --- | --- |
| Lint | `python -m ruff check app tests evaluation tests/evaluation` | **All checks passed** (exit 0) |
| Evaluation tests | `python -m pytest tests/evaluation -q` | **39 passed** (exit 0) |
| MQTT integration | `python scripts/run_mqtt_integration.py -q` | **7 passed** (exit 0) |
| Full backend suite | `python -m pytest -p no:cacheprovider --override-ini addopts= -m "not mqtt_e2e and not mqtt_integration"` | **776 passed, 10 skipped, 11 deselected** (exit 0, 602.03 s) |

The default `addopts` (`pyproject.toml` line 60) deselects `mqtt_e2e` and
`mqtt_integration`, so the ordinary suite stays hermetic; the broker-gated MQTT
suite is run explicitly above.

> Frontend gates (`npx vitest run`, `npx tsc --noEmit`, `npx eslint .`,
> `npx playwright test`) are recorded in the roadmap from the Phase A–D work and
> were **not** re-run in this session.

---

## Status roll-up

| Phase | Verdict |
| --- | --- |
| A | Implemented; tests present; process-local limitation documented. |
| B | Implemented; drift is observable; running backend/hosted DB intentionally untouched. |
| C | Implemented **and verified this session** (7/7). |
| D | Implemented and previously verified (7/7); not re-run here; three honest gaps listed. |
| E | Partially implemented; **multi-worker safety unverified**. |
| F | Grounding metric implemented; **offline RAG evaluation not started**. |
