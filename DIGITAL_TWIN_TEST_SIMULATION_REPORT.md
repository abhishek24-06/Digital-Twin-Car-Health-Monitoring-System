# Digital Twin Car Health Monitoring — Test Simulation Report

**Date (UTC):** 2026-10-14
**Environment:** local development machine (Windows, PowerShell)
**Method:** automated API/unit/integration tests + isolated end-to-end scenarios
**Verdict scale:** PASS / FAIL / BLOCKED / NOT IMPLEMENTED (no result is fabricated; illustrative examples are labeled as such)

---

## 1. Executive summary

- **Backend:** 297 existing tests passed across intelligence, repositories, telemetry/health/alert services, RAG, agent, and workflow/alert API routes; `ruff` clean. **12 new API safety tests added and passing** (`backend/tests/api/test_qa_simulation_safety.py`).
- **Frontend:** typecheck clean, lint clean, **216/216 component/hook tests passed**.
- **Browser E2E (isolated stack, disposable DB):** **13/13 passed**, including all 8 vehicle tabs rendering against the live backend, a mock-LLM agent diagnosis in the browser (38.9 s), auth rejection, cross-account 403/404, phone layout, and a zero-console-error sweep. A dashboard screenshot was captured (kept outside the repo).
- **Rule engine:** 10 scripted anomaly cases executed with actual outputs; simulator-engine triad (normal / high_temperature / low_battery) reproduced a genuine **60/100 attention** assessment end to end through the real simulator + real rule engine.
- **RAG models (local cache, no DB):** BGE-M3 first load + 32-doc encode 27.2 s; bge-reranker-v2-m3 first rerank of 30 short docs 17.2 s (≈2 s weight load inside it), warm rerank 7.3 s; process-wide adapter cache identity confirmed True/True.
- **Perf (isolated test DB, sequential):** ingest 200/200 avg 2.21 ms (p95 2.95 ms, 451 rps); list 20/20 avg 2.32 ms (p95 6.80 ms); health analysis 5/5 avg 15.3 ms; cleanup verified, schema removed afterwards.
- **Fault prediction model: NOT IMPLEMENTED** — the system uses deterministic rules + an LLM diagnosis agent; verified by code search (no sklearn/torch/predictive model in `app/intelligence` or the agent graph).
- **No app-code defects were found by this run.** Two failures seen during the run were bugs in the newly written test script itself (fixed, documented in §8). Follow-ups: `npm audit` reports 2 high-severity prod-dependency advisories (fix available, not applied — would modify lockfiles); live-LLM diagnosis and populated-corpus RAG retrieval were deliberately BLOCKED (cost/production-write risk, §10).

## 2. Environment and safety/isolation checks

| Check | Result |
|---|---|
| Running stack during tests | Frontend :3000, backend :8000, Postgres :5432, Mosquitto :1883 listening — treated as **production, never written to** |
| Backend test target | `TEST_DATABASE_URL` unset → `tests/conftest.py` default `postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_test`, with a fail-closed guard refusing Supabase/pooler/AWS hosts |
| Perf-script guard | Script asserts `digital_twin_test` in the URL and **refused to run** when the ambient `DATABASE_URL` pointed elsewhere (verified refusal once); schema created/dropped via test-harness metadata DDL only, rows cleaned, `remaining_rows=0` |
| E2E isolation | `run_e2e_backend.py` fails closed unless the DB is loopback + named exactly `digital_twin_browser_test`; mock LLM providers; MQTT pointed at a dead port; user's :3000/:8000 untouched (verified listening after teardown) |
| RAG microbench | No database, no network model download (local HF cache hit); read-only inference |
| Simulator scenarios | `SimulationEngine` driven in-process; no MQTT publish, no DB writes |
| Secrets | Presence-only checks (e.g. `openrouter_key_present=True`); no values printed, none in logs or this report |
| Protections left intact | Auth, validation (`extra="forbid"`), reranking, rate limiting all enabled; nothing disabled to make tests pass |

## 3. Architecture and implementation discovered

- **Ingestion:** `POST /vehicles/{id}/telemetry` (`TelemetryCreate`: tz-aware-or-naive `timestamp` required, 11 nullable sensors, range bounds, `extra="forbid"`) and MQTT `TelemetryMessage` (stricter: rpm ≤ 10000, speed ≤ 400, tz-aware enforced) → subscriber batch validate/persist → `telemetry_records` (indexed `(vehicle_id, timestamp)`, partial unique `(vehicle_id, source_event_id)`).
- **Retrieval:** `GET /vehicles/{id}/telemetry` (newest-first pages, `total`), `GET …/telemetry/stream` (SSE, exclusive-timestamp cursor), `GET …/historical-analytics` (bounded window analytics).
- **Simulator:** `SimulationEngine` drive-cycle state machine (`OFF/STARTING/IDLE/ACCELERATING/CRUISING/DECELERATING`), scenarios `normal`, `high_temperature` (coolant→115, oil→108), `low_battery` (11.9 V run / 11.4 V rest), `high_engine_load` (load ×1.5); 1 s cadence, wall-clock UTC stamps, QoS 1, no retain.
- **Health:** window statistics → 14 metric rules + 5 data-state findings (`app/intelligence/rules.py`) → score = 100 − capped category penalties, thresholds 80/60 (`scoring.py`) → snapshot persisted with full `context_json`; historical (`POST …/health/analyze`, 15-min window, min 10 samples) vs current-session (`GET …/health/live`, active-run evidence + 30-sample/30-s/50%-coverage/15-s-age gate).
- **Anomaly detection:** the deterministic rule engine above (coolant/oil max, battery min/max, load mean, rpm mean, fuel min, rapid rises, gap, coverage). **No statistical/ML anomaly detector exists.**
- **Fault prediction model:** none. Diagnosis = LangGraph agent (OpenRouter primary / Groq fallback, 60 s timeout, 2 retries) grounded in health context + RAG evidence, with cooldown dedup.
- **RAG:** admin upload (`POST /rag/documents`), chunk → BGE-M3 embed (1024-d) → pgvector hybrid search → bge-reranker-v2-m3 rerank (top 30) → citations; `GET /rag/search`, `GET /rag/health`; recent fix caches adapters process-wide and runs model work off the event loop.
- **Frontend:** vehicle workspace tabs (Overview / Live Health / Simulation / Analytics / Telemetry / AI Diagnosis / History / Alerts), workflow monitor, `ApiError` envelope mapping (`Cannot reach…` = rejected fetch).
- **Tests:** backend pytest (hermetic unit + local-DB integration), frontend vitest (216), Playwright e2e (isolated servers + disposable DB).

## 4. Test methodology for both techniques

- **Technique A (automated):** ran the existing suites unmodified (commands + exit codes in §9); added one kept API test file (12 tests) after confirming fixtures/conftest isolation; no app code touched.
- **Technique B (scenarios):** (a) Playwright suite against isolated backend+frontend+disposable DB (13 tests, incl. screenshot); (b) offline simulator-engine → rule-engine triad; (c) pure rule-engine anomaly battery; (d) isolated real-model RAG timing; (e) isolated-DB perf run with cleanup. Live simulator→MQTT→prod-DB and live-LLM diagnosis were BLOCKED by safety rules (prod writes / API cost); documented with substitutes in §10.

## 5. TC results table

| ID | Requirement | Inputs & procedure | Expected | Actual | Verdict | Evidence |
|---|---|---|---|---|---|---|
| TC-01 | Valid telemetry round-trip | `POST /vehicles/{id}/telemetry` full 11-field payload; `GET` list; unknown UUID; empty vehicle | 201 + echo; retrievable newest-first; 404; `total:0` | 201 with matching vehicle_id/rpm/timestamp; list `total:1`; 404 no traceback; 200 `total:0` | **PASS** | `test_qa_simulation_safety.py` (4 tests), 12/12 file pass |
| TC-02 | Preprocessing contract | Missing ts; `rpm:"fast"`; `ts:"not-a-timestamp"`; rpm −5 / coolant 500 / fuel 101; unknown field; nulls + out-of-order insert | 422s; nulls stored null; timestamp ordering | All 422s; nulls persisted null; rows returned chronologically despite reverse insert order | **PASS** | Same file (5 tests). Note: `+00:00` input is Z-normalized in responses (observed, by design) |
| TC-03 | Health dashboard | 216 component tests; e2e 8-tab sweep; screenshot; empty-state + failure tests | Readings/score/status visible; honest empty/error states; units match API | 216 pass; 8 tabs render live; screenshot captured; empty/failure tests pass (e.g. missing snapshot→null, 502-no-provider surfaced) | **PASS** | vitest 216/216; e2e 13/13; `qa-dashboard.png` (59 KB, outside repo); §6 |
| TC-04 | Anomaly detection | Engine battery: normal, coolant 115/105, batt 11.4/10.0, load 80, rpm 5000, fuel 4, 3-sample, 0-sample; simulator triad | Exact rule+severity; negatives clean; insufficient → provisional | All matched (e.g. 115→COOLANT critical 70 attention; 5000→RPM_UNUSUAL warning 90 healthy; 0 samples→no_data/None). Simulator: normal 100 healthy; high_temp **60 attention** (COOLANT critical + OIL warning); low_batt 90 + warning | **PASS** | `qa_tc04_rules.py` output; `qa_scenarios.py` output (§6) |
| TC-05 | Fault prediction model | Code search `app/intelligence` + agent graph for sklearn/torch/predict | A real model or honest NOT IMPLEMENTED | No predictive model anywhere; only deterministic rules + LLM diagnosis | **NOT IMPLEMENTED** (by design) | Zero matches for sklearn/joblib/pickle/torch/`predict(` in intelligence; agent `nodes.py` has no predictor |
| TC-06 | Diagnostic explanation | Mock-LLM e2e diagnosis (38.9 s); grounded-diagnosis + 502 + empty-state component tests; agent unit tests (87 incl. RAG-unit degradation paths) | Understandable, evidence-linked answer; clear failure/insufficient-data messaging | E2E diagnosis card renders; components pin 502/404/empty behavior; `ManufacturerGuidanceTool` `_fail` reasons (no-vehicle/rag-disabled/retrieval-error/no-evidence) tested | **PASS with limits** | e2e test #5; `vehicle-diagnosis-view.test.tsx`; live-LLM call BLOCKED (cost + prod-write risk) |
| TC-07 | RAG retrieval | Unit + query-workflow + repository integration tests; RAG-disabled 503 test; isolated real-model timing (encode 32 docs, rerank 30) | Embedding ok; evidence relevant; rerank per config; citations to real sources; safe empty/failure handling | Suites pass; disabled→explicit 503; real models: load+encode 27.2 s, first rerank 17.2 s, warm rerank 7.3 s, scores finite in band, cache identity True/True | **PASS with limits** | tests/rag (in 87-pass run); new 503 test; microbench output. Full-corpus retrieval NOT EXECUTED (no corpus in test DB; prod off-limits) |
| TC-08 | Error handling | 401 no-auth; 403/404 cross-owner; 404 unknown vehicle; 422 shapes; traceback scan; existing SSE-cancel / monitor-survives-failure / rate-limit tests | Clean envelopes, correct codes, no traces/secrets, recovery | All asserted (incl. `"Traceback" not in text`); suites covering cancel/survival pass; handlers sanitize (500→"Internal server error", DB details server-side only) | **PASS** | New file (4 tests); `test_workflow_routes.py`; monitor/agent suites |
| TC-09 | Performance | Isolated test DB, sequential: 200 ingests, 20 page reads, 5 analyses; real-model RAG timing; no concurrency ramp | Measured + proposed targets (no SLOs exist in-repo) | ingest avg 2.21 ms p95 2.95 ms 451 rps; list avg 2.32 ms p95 6.80 ms; analyze avg 15.3 ms; RAG warm rerank 7.3 s (short docs; 512-token chunks cost more) | **PASS with limits** | `qa_tc09_perf.py` output; microbench. HTTP-level + concurrent load NOT EXECUTED |
| TC-10 | Security | Hardcoded-secret grep; .env ignore; auth-header logging; error sanitization; authN/Z tests; `npm audit` | No secrets in code/logs; envelopes clean; checks enforced; dep risks listed | Zero hardcoded secrets; `.env` ignored (root + backend); no header logging; metadata redaction list verified; 403/404 + ownership tests pass; **npm audit: 2 high (Next.js SSRF image-optimization; source-map-js event-loop DoS) + moderate/low Next advisories, fix available, not applied** | **PASS with findings** | Paths/lines in §7; audit output |

## 6. Detailed scenario results

- **TC-04 battery (actual output):** normal→`100.0/healthy/[]`; coolant115→`70.0/attention/[COOLANT_TEMP_HIGH critical]`; coolant105→`90.0/healthy/[warning]`; batt11.4→`90.0/healthy/[BATTERY_VOLTAGE_LOW warning]`; batt10.0→`70.0/attention/[critical]`; load80→`70.0/attention/[ENGINE_LOAD_HIGH critical]`; rpm5000→`90.0/healthy/[RPM_UNUSUAL warning]`; fuel4→`70.0/attention/[FUEL_LEVEL_LOW critical]`; 3 samples→`100.0/limited_data/provisional=True/[LIMITED_DATA, LOW_DATA_COVERAGE]`; 0 samples→`None/no_data/[INSUFFICIENT_DATA]`.
- **Simulator triad (actual output):** normal `coolant_max=90.0 → 100.0/healthy/[]`; high_temperature `coolant_max=115.0, oil_max=107.9 → 60.0/attention/[COOLANT critical, OIL warning]` (temperature 30+10=40 penalty — a genuine 60/100 reproduction); low_battery `batt_min=11.64 → 90.0/healthy/[BATTERY warning]`.
- **E2E (13/13, 1.8 min total):** redirect, wrong-password, 8-tab sweep (11.5 s), mock-LLM diagnosis (38.9 s), cross-account denial, 375 px overflow, zero-error sweep, 5 workflow-filter specs, dashboard screenshot.
- **Empty/insufficient UI:** missing snapshot→null (not error), missing diagnosis→empty state, no-provider 502 surfaced, stale feed flagged without reusing scores, cross-vehicle data never shown while loading.

## 7. Performance measurements and proposed target comparisons

All targets below are **proposed** (no SLOs exist in-repo). Sequential local load, isolated test DB unless noted.

| Operation | n | Result | Proposed target | Met? |
|---|---|---|---|---|
| Telemetry ingest (service) | 200 | avg 2.21 ms, p50 2.02, p95 2.95, p99 6.67, 451 rps, 0 failed | p95 < 25 ms | Yes |
| Telemetry list p.1×50 (service) | 20 | avg 2.32 ms, p50 2.01, p95 6.80 | p95 < 50 ms | Yes |
| Health analysis end-to-end | 5 | avg 15.3 ms, p50 13.6, p95 21.6 (score 100/healthy) | p95 < 500 ms | Yes |
| BGE-M3 load + encode 32 docs (CPU) | 1 | 27.2 s (35.3 s first run) | one-time cost, cached | n/a |
| bge-reranker-v2-m3 rerank 30 short docs (CPU) | 2 | 17.2 s cold (incl. ~2 s load), 7.3 s warm | warm p95 < 60 s (hardware-dependent) | Yes (short docs) |
| Agent diagnosis (browser, mock LLM) | 1 | 38.9 s end-to-end | < 180 s | Yes |
| Full HTTP latency / concurrent load | — | **not measured** | needs dedicated harness | n/a |

RAG note: production chunks at 512 tokens cost substantially more CPU inference than the short-doc numbers above; reranking was correctly **not** bypassed. Complete HTTP latency (not only workflow completion) was not measured — needs a load harness against an isolated stack.

## 8. Defects discovered, root causes, and fixes

- **App-code defects found by this run: none.** All suites green on first execution except the two items below.
- **Test-script bugs (mine, fixed, not app defects):** (1) expected `+00:00` timestamp echo but the API Z-normalizes datetimes — corrected expectations to `…20Z`; (2) passed `json=` to httpx `GET` (unsupported kwarg) — split into separate GET/POST calls. File now 12/12 green. Kept as regression tests.
- **Pre-existing follow-ups surfaced (not introduced, not fixed here):** exact-threshold boundary tests absent (all comparisons strict `>`/`<` except rapid-rise `>=` — behavior verified by reading, unpinned by tests); agent cooldown-dedup path untested; `npm audit` highs (§5 TC-10).

## 9. Regression test results

| Command | Exit | Result |
|---|---|---|
| `pytest tests/intelligence tests/repositories` | 0 | 99 passed |
| `pytest tests/services/{telemetry,vehicle_health,health_monitor,alert}` | 0 | 78 passed |
| `pytest tests/rag/test_rag_unit.py tests/rag/test_rag_query_workflow.py tests/agent` | 0 | 87 passed |
| `pytest tests/api/test_workflow_routes.py tests/api/test_alert_routes.py` | 0 | 33 passed |
| `pytest tests/api/test_qa_simulation_safety.py` (new) | 0 | 12 passed (after the 2 test-script fixes above) |
| `ruff check app/ tests/` | 0 | clean |
| `npm run typecheck` / `npm run lint` | 0 / 0 | clean |
| `npm run test` (vitest) | 0 | 32 files, 216 passed |
| `npx playwright test` (isolated stack, disposable DB) | 0 | 13 passed |

## 10. Known limitations and tests not executed

1. Live simulator→MQTT→production-DB loop: BLOCKED (would write production telemetry). Substituted with in-process engine triad + existing subscriber integration tests.
2. Live-LLM diagnosis: BLOCKED (API cost + production diagnosis writes; keys present but unused). Substituted with mock-provider e2e + agent unit tests + verified 502/empty paths.
3. Populated-corpus RAG retrieval/citations: NOT EXECUTED (no corpus in test DB; prod documents off-limits). Unit/integration + disabled-path + isolated model timing cover the rest.
4. HTTP-level latency and concurrent load: NOT EXECUTED (needs an isolated load harness).
5. Browser screenshot of a *fault* state: not captured (scenario specs cover healthy/empty/auth paths; fault UI paths covered by component tests).
6. Python dependency audit (pip-audit/safety): not run (tooling not installed; installing would modify the venv).

## 11. Steps to reproduce the test run

```powershell
# Backend suites (isolated test DB digital_twin_test; destructive only there)
cd backend
.\.venv\Scripts\python.exe -m pytest tests/intelligence tests/repositories -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/services/test_telemetry_service.py tests/services/test_vehicle_health_service.py tests/services/test_health_monitor_service.py tests/services/test_alert_service.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/rag/test_rag_unit.py tests/rag/test_rag_query_workflow.py tests/agent -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/api/test_workflow_routes.py tests/api/test_alert_routes.py tests/api/test_qa_simulation_safety.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app/ tests/ -q
# Rule-engine battery / scenario triad (no DB): python qa_tc04_rules.py, qa_scenarios.py
# RAG model timing (local HF cache, no DB): python qa_rag_microbench.py
# Perf (refuses non-test DB; cleans up + drops schema): $env:DATABASE_URL='postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_test'; python qa_tc09_perf.py
# Frontend
cd ../frontend
npm run typecheck; npm run lint; npm run test
# Browser E2E needs the .e2e-tmp nested-copy workaround while a dev server runs on :3000
# (Next.js allows one dev server per project dir): copy frontend (minus node_modules/.next)
# to frontend/.e2e-tmp, start run_e2e_backend.py on :8010, start next dev there on :3010
# with NEXT_PUBLIC_API_URL=http://127.0.0.1:8010/api/v1, then E2E_REUSE_SERVERS=1 npx playwright test
```

## 12. Final recommendation and prioritized follow-up actions

1. **Apply `npm audit fix` for the 2 high-severity prod advisories** (Next.js SSRF, source-map-js DoS) in a maintenance window with a lockfile review + test rerun. (Untouched here to avoid unrelated modifications.)
2. **Add exact-boundary rule tests** (e.g. coolant exactly 100.0/110.0, coverage exactly 0.5) — the strict-operator behavior is currently proven only by inspection.
3. **Build an isolated load harness** (test-DB backend + k6/pytest-benchmark) to measure HTTP p95 under concurrency before setting SLOs; keep reranking enabled in all benchmarks.
4. **Seed a disposable corpus** in `digital_twin_browser_test` so RAG retrieval/citation E2E can run without touching production documents.
5. **Approve-or-reject a single live-LLM diagnosis run** against the isolated stack for TC-06 completeness (small API cost).
6. **No production remediation required** — no app defect, no data corruption, and no schema/config change resulted from this run. The one kept code artifact is the new test file `backend/tests/api/test_qa_simulation_safety.py`; all scratch scripts live outside the repo and the e2e stage was fully torn down (user's :3000/:8000 verified still listening).
