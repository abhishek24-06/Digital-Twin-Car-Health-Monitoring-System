# Digital Twin — API & Report Field Map (supporting artifact)

**Companion to:** `DIGITAL_TWIN_SYSTEM_AUDIT_2026-10-11.md`
**Date:** 2026-10-11 · Prefix `/api/v1` · Live OpenAPI: **34 paths** (tag list empty in the live document)

Source of truth: live `http://127.0.0.1:8000/openapi.json` + source routes. Labels: Verified / Inferred / Not verified. No credentials reproduced.

---

## 1. Key endpoints (Verified against live OpenAPI + source)

| Method & path | Purpose | Live/Hist | Run filter | Side effects | Source |
|---|---|---|---|---|---|
| `POST /auth/login` | issue tokens | — | — | refresh token row | `app/api/routes/auth.py` |
| `GET /health` | service liveness | — | — | none | `app/main.py` |
| `GET /health/db` | DB reachability | — | — | none | `app/main.py` |
| `GET /vehicles` | list owned | — | — | none | `app/api/routes/vehicles.py` |
| `GET /vehicles/{id}` | vehicle detail | — | — | none | `vehicles.py` |
| `POST /vehicles/{id}/telemetry` | REST ingest | — | **NULL** | insert row(s) | `telemetry.py:26-40` |
| `GET /vehicles/{id}/telemetry` | list rows | historical | none | none | `telemetry.py` |
| `GET /vehicles/{id}/telemetry/stream` | SSE rows | historical | cursor | none | `telemetry.py:121-161` |
| `POST /vehicles/{id}/health/analyze` | windowed analysis | **historical** | **none** | **persists snapshot** | `vehicle_health.py:24-45` |
| `GET /vehicles/{id}/health` | latest snapshot | **historical** | none | none | `vehicle_health.py:48-65` |
| `GET /vehicles/{id}/health/history` | snapshot list | historical | — | none | `vehicle_health.py:68-103` |
| `GET /vehicles/{id}/health/live` | live current session | **live** | **active run** | **persists snapshot** | `vehicle_health.py:127-254` |
| `GET /vehicles/{id}/historical-analytics` | aggregates | **historical** | segments | none | `historical_analytics.py:29-54` |
| `GET/POST /vehicles/{id}/simulation` (+`/restart`) | control | live | run mint | spawn/stop | `app/api/routes/simulation.py` |
| `GET /simulations` | list statuses | live | — | none | `simulation.py` |
| `GET /workflow/status` | aggregate pipeline | live | — | none | `app/api/routes/workflow.py` |
| `GET /workflow/state` | per-vehicle derived stages | live | — | none | `workflow.py` |
| `GET /workflow/events/recent` | buffered events | live | — | none | `workflow.py` |
| `GET /workflow/events/stream` | SSE events | live | — | none | `workflow.py` |

**Ownership:** every vehicle-scoped route enforces ownership via `ensure_vehicle_access` (404 for unowned). Verified live (unowned demo vehicle → 404).

---

## 2. Health context field map (what the report displays)

`HealthContextResponse` / persisted `context_json` (`backend/app/schemas/vehicle_health.py`, `app/intelligence/context.py`):

| Field | Meaning | Computed by |
|---|---|---|
| `health_score` | 100 − capped per-category penalties, clamped 0–100 | `app/intelligence/scoring.py:59-102` |
| `health_status` | healthy ≥80 / attention 60–79.99 / critical <60 / unknown | `scoring.py:49-56` |
| `confidence` | `0.10 + 0.90*(0.30·coverage + 0.25·duration_ratio + 0.25·sample_sufficiency + 0.20·completeness)` | `scoring.py:105-124` |
| `data_sufficiency` | `no_data` / `limited_data` / `sufficient_data` | `engine.py:188-286` |
| `provisional` + `provisional_rating` | live gate failure indication | `engine.py:91-149, 188-286` |
| `analysis_window` | `{window_start, window_end, window_minutes}` — **the snapshot's own window** | `engine.py` / service |
| `data_quality.sample_count` | rows in the snapshot window | `engine.py:43-88` |
| `data_quality.expected_sample_count` | `ceil(window_seconds / expected_interval_seconds)` | `engine.py:43-88` |
| `data_quality.coverage_ratio` | `min(1, sample_count / expected)` | `engine.py:43-88` |
| `data_quality.duration_seconds` | last − first | `engine.py:43-88` |
| `data_quality.max_gap_seconds` | largest inter-sample gap | `engine.py:43-88` |
| `data_quality.timestamp_order_valid` | monotonic timestamps | `engine.py:74-76` |
| `statistics[m]` | min/max/mean/median/std_dev/last/count | `statistics.py` |
| `findings[]` | `{rule, severity, category, metric, observed, threshold, message}` | `rules.py` |
| `score_details` | `starting_score`, `total_penalty`, category breakdown | `scoring.py` |
| `trends[]` | direction/slope/strength per metric | `trends.py` |
| `baselines[]` | historical baseline comparison (live path excludes current run) | `baselines.py` |
| `simulation_run_id` | run identity, or `null` for legacy/multi-run snapshots | service |

---

## 3. Score & penalty model (Verified)

- Base 100; penalties **info 0 / warning 10 / critical 30** (`scoring.py:39`).
- Accumulated per **category**, each capped at **40** (`scoring.py:42`).
- Status thresholds `scoring.py:45-46`.
- Rule thresholds centralized in `RuleThresholds` (`rules.py:26-44`): coolant warn 100 / crit 110; oil warn 100 / crit 110; rapid temp rise ≥8 °C; battery low 12.0/10.5; engine-load mean 40/60; rpm mean 4500; fuel 15/5; data-quality `TELEMETRY_GAP` at 3× interval and `LOW_DATA_COVERAGE` at coverage <0.5 (info).

**Worked example (BMW, live):** temperature findings 30+10+10+10=60 → capped 40; data-quality 0 ⇒ score **60**, status **attention**; confidence **0.5391** (coverage 0.2017, duration_ratio 0.7077, sample_sufficiency 0.2017, completeness 1.0).

---

## 4. Frontend field provenance (Verified by source)

| Rendered value | Backend source | Frontend file |
|---|---|---|
| Score / status ring & badge | `health_score`, `health_status` | `components/health/health-visuals.tsx` |
| Confidence % | `confidence` | `health-summary-panel.tsx` |
| Sample count / coverage | `data_quality.*` | `vehicle-health-view.tsx` |
| "Analysis window" text | `analysis_window.window_minutes` | `health-summary-panel.tsx:159-165` |
| Window **selector** | local state default `"60"` (decoupled) | `health-summary-panel.tsx:32,144-149` |
| Findings list | `findings[]` | `findings-list.tsx` |
| Statistics table | `statistics[]` | `vehicle-health-view.tsx` |
| Trends | `trends[]` | `vehicle-health-view.tsx` |
| Metrics tiles (newest) | `GET /telemetry` (latest row) | `metric-tile.tsx` |

---

## 5. Report consistency rules (verified behavior)

1. Within a **single snapshot**, score, confidence, coverage, findings, statistics and trends come from the **same** window/sample list → internally consistent.
2. The **selector** does **not** drive `GET /health`; it only drives `POST /health/analyze`. So the selector can legitimately differ from the displayed snapshot's window → **cross-section inconsistency**.
3. **`analysis_window` = the snapshot's window**, not the requested/selected window.
4. **`simulation_run_id = null`** means the snapshot spans legacy/multiple runs (historical), which the UI does not currently disclose.

---

## 6. Gaps / unclear in the live OpenAPI

- The live OpenAPI declares **no tags** (tag list empty), reducing discoverability.
- Some SSE endpoints are described but client cancellation/poll behavior is only evident from source, not the schema.
- Error response schemas are generic; specific 4xx/5xx bodies are documented only in code.
