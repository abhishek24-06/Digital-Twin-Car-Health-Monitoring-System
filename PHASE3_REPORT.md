# Phase 3 Engineering Report — Vehicle Health Context (Deterministic)

Project: Digital Twin Car Health Monitoring Platform (Backend)
Phase: 3 — deterministic, explainable vehicle health analysis
Repo location: `C:\Users\Abhishek\Desktop\Digital Twin\backend`
Date: 2026-09-20

---

## 0. Summary

Phase 3 is **complete**: a deterministic, explainable health-intelligence
subsystem that analyses a configurable historical telemetry window
(statistics → trends → baselines → rules → scoring → confidence), persists
every analysis as an **immutable JSONB snapshot** in PostgreSQL, and exposes it
via a REST API. No LLM, no ML, no RAG, no pgvector, no new infrastructure.

Full regression gate: **196 passed, 1 deselected (mqtt_e2e), ruff clean,
alembic head `a1b2c3d4e5f6`**.
Live broker verification across all four simulator scenarios achieved: coolant
**critical**, battery **warning**, engine-load **warning**, normal **healthy**.

---

## 1. Constraint compliance

| Constraint (spec §1–§2)                      | Status |
| -------------------------------------------- | ------ |
| No LLM / LangChain / LangGraph / OpenAI/Gemini/Claude | ✅ not present anywhere |
| No RAG / embeddings / pgvector / Supabase    | ✅ |
| No Redis / Celery / Kafka / scheduled jobs   | ✅ (analysis is explicit API-triggered only) |
| No dashboard / frontend / ML prediction      | ✅ |
| Deterministic + explainable output           | ✅ (pure arithmetic, thresholds centralized) |
| No new infrastructure services               | ✅ (PostgreSQL + existing Mosquitto only) |
| Don't break Phase 1/2                        | ✅ 196 tests, all Phase 1/2 tests unchanged & green |

---

## 2. Architecture

```
Mqtt/REST ingestion (unchanged, Phase 2)
        │
        v
PostgreSQL (telemetry_records)
        │  (window + baseline read)
        v
VehicleHealthService  ── translates ORM → TelemetryPoint only
        │
        v
HealthAnalysisEngine (app/intelligence)   ⇐ transport-agnostic, typed
   compute_data_quality → statistics → trends → baselines → rules
   → score_findings → compute_confidence → HealthContext
        │
        v
HealthSnapshotRepository → vehicle_health_snapshots (JSONB, immutable)
```

- The intelligence layer is **pure**: it consumes `TelemetryPoint(timestamp,
  values)` and never touches the DB, MQTT, or HTTP. The service is the only
  translator.
- Historic data (via repository), MQTT data, REST data, replay and fixtures all
  exercise the identical path.

---

## 3. Modules delivered

| Module | Responsibility |
| ------ | -------------- |
| `app/intelligence/models.py` | `HealthContext`, `MetricStatistics`, `TrendInsight`, `BaselineInsight`, `Finding`, `DataQuality`, `ScoreDetails`, `AnalysisWindow`, `TelemetryPoint`; schema v1.0, SUPPORTED_METRICS + units |
| `app/intelligence/statistics.py` | Robust per-metric statistics; never emits NaN/Inf; missing/non-finite→ignored; sample std-dev (n−1); linear-interp percentiles |
| `app/intelligence/trends.py` | OLS slope (units/s) + `normalized_slope = slope·span/|mean|`; direction (ε=0.01); strength none<0.01, weak<0.08, moderate<0.25, strong≥0.25 |
| `app/intelligence/baselines.py` | Vehicle's own history: median center + `1.4826·MAD` spread; `|dev|>2.0` ⇒ elevated/depressed; `insufficient_history` otherwise |
| `app/intelligence/rules.py` | `RuleThresholds` (single source of truth) + `HealthRuleEngine` (see §4) |
| `app/intelligence/scoring.py` | Score/status/confidence model (see §5) |
| `app/intelligence/context.py` | `build_context()`, UTC now |
| `app/intelligence/engine.py` | `HealthAnalysisEngine.analyze(...)` orchestration + `compute_data_quality` |
| `app/models/health_snapshot.py` | `vehicle_health_snapshots` model, JSONB `context_json`, composite indexes, FK cascade |
| `app/repositories/health_snapshot_repository.py` | create / get_by_id / latest / paginated list(+time filters) |
| `app/repositories/telemetry_repository.py` | **added** `get_recent_telemetry` (windowed, ASC, bounded) |
| `app/services/vehicle_health_service.py` | analyze / latest / history orchestration + persistence commit |
| `app/schemas/vehicle_health.py` | `HealthContextResponse` (reuses intelligence models) + `HealthSnapshotItem` |
| `app/api/routes/vehicle_health.py` | `POST /analyze`, `GET`, `GET /history` |
| `alembic/versions/a1b2c3d4e5f6_...py` | migration (revises `7e38f4f3d70b`) |
| `config.py`, `.env.example` | 5× `HEALTH_*` settings |
| tests | `tests/intelligence/*`, `tests/repositories/test_health_snapshot_repository.py`, `tests/services/test_vehicle_health_service.py`, `tests/api/test_vehicle_health.py` |

---

## 4. Rule engine thresholds (centralized)

`RuleThresholds` defaults (documented in README §12; configurable):

| Rule ID | Condition | Warning | Critical |
| ------- | --------- | ------- | -------- |
| `COOLANT_TEMP_HIGH` | max coolant | > 100 °C | > 110 °C |
| `OIL_TEMP_HIGH` | max oil | > 100 °C | > 110 °C |
| `BATTERY_VOLTAGE_LOW` | min battery | < 12.0 V | < 10.5 V |
| `BATTERY_VOLTAGE_HIGH` | max battery | > 15.0 V | — |
| `ENGINE_LOAD_HIGH` | mean load | > 40 % | > 60 % |
| `RPM_UNUSUAL` | mean rpm | > 4500 | — |
| `FUEL_LEVEL_LOW` | min fuel | < 15 % | < 5 % |
| `RAPID_COOLANT_RISE` / `RAPID_OIL_TEMP_RISE` | last−first | ≥ 8 °C | — |
| `TELEMETRY_GAP` | max gap | > interval×3 (info) | — |
| `LOW_DATA_COVERAGE` | coverage | < 0.5 (info) | — |
| `INSUFFICIENT_DATA` | sample count | < `HEALTH_MINIMUM_SAMPLES` | — |

Findings are factual ("coolant temperature is significantly elevated"), never
a diagnosis ("water pump failed").

---

## 5. Scoring, status & confidence model

- Score = `clamp(100 − Σ penalties, 0, 100)`; penalties `info=0, warning=10,
  critical=30`; **per-category cap 40**.
- Status: `≥80 healthy`, `60≤<80 attention`, `<60 critical`; `score=None
  → unknown` (insufficient data).
- Confidence (0–1, round 4):
  `0.10 + 0.90·(0.30·coverage + 0.25·duration_ratio + 0.25·sample_sufficiency + 0.20·completeness)`.
  This is confidence **in the telemetry-based assessment**, explicitly NOT the
  probability the vehicle is healthy.

---

## 6. Data quality & snapshot design

- `DataQuality` reports `coverage_ratio`, expected vs actual sample count,
  duration, `max_gap_seconds`, order validity, missing-sample estimate.
- Snapshots are **immutable historical evidence**: re-analysis always creates a
  new row; existing rows are never mutated. Top-level queryable columns
  (`health_score`, `health_status`, `confidence`, `sample_count`, window bounds)
  + full `context_json` (JSONB).
- Indexes: `(vehicle_id, generated_at)` and `(vehicle_id, health_status,
  generated_at)`; FK `vehicle_id → vehicles.id ON DELETE CASCADE`
  (verified live in the schema).
- Bounded reads: window row estimate `≈ (window_sec/interval)·2 + 100`, so a
  6-hour baseline fetch cannot balloon.

---

## 7. REST API contract

| Method | Path | Behaviour |
| ------ | ---- | --------- |
| POST | `/api/v1/vehicles/{id}/health/analyze` | analyze window (`window_minutes` Query 1–1440, default `HEALTH_ANALYSIS_WINDOW_MINUTES`), persist snapshot, return full context (200) |
| GET | `/api/v1/vehicles/{id}/health` | latest context (200); 404 when none or vehicle missing |
| GET | `/api/v1/vehicles/{id}/health/history` | paginated (`page`, `page_size ≤ 100`, optional `start_time`/`end_time` on `generated_at`), newest first |

- 404 / 422 / 500 semantics consistent with Phase 1/2 (see README §18).
- OpenAPI confirms exactly three new paths under `/vehicles/{vehicle_id}/health`.

Settings added (with defaults):
`HEALTH_ANALYSIS_WINDOW_MINUTES=15`, `HEALTH_MINIMUM_SAMPLES=10`,
`HEALTH_EXPECTED_INTERVAL_SECONDS=1.0`, `HEALTH_BASELINE_WINDOW_MINUTES=360`,
`HEALTH_BASELINE_MINIMUM_SAMPLES=5`.

---

## 8. Migration verification (dev DB)

```
7e38f4f3d70b → a1b2c3d4e5f6 "create vehicle_health_snapshots"     (upgrade)
a1b2c3d4e5f6 → 7e38f4f3d70b                                        (downgrade -1)
7e38f4f3d70b → a1b2c3d4e5f6 (head)                                 (upgrade again)
```

Down/up cycle verified; table + indexes present in dev database.

---

## 9. Test results

### Phase 3 test files (new)

| Suite | File(s) | Focus |
| ----- | ------- | ----- |
| Unit | `tests/intelligence/test_statistics.py` (11), `test_trends.py` (7), `test_baselines.py` (8), `test_rules.py` (17), `test_scoring.py` (11), `test_engine.py` (9) | engine math, thresholds, degradation paths, JSON serialisability |
| Repo | `tests/repositories/test_health_snapshot_repository.py` (8) | create/latest/list/filters/isolation/FK |
| Service | `tests/services/test_vehicle_health_service.py` (11) | analyze → persist, window respect, 404s, history, repeat-analysis immutability |
| API | `tests/api/test_vehicle_health.py` (10) | analyze/latest/history contracts, 404/422, high-temp finding |

**Full suite:** `196 passed, 1 deselected (mqtt_e2e)` — no Phase 1/2
regressions. **Ruff:** `check .` clean; `format --check .` 86/86.

---

## 10. Live verification (real broker → Postgres → analysis)

Environment: Mosquitto Windows service (127.0.0.1:1883, anonymous), PostgreSQL
17, FastAPI on 127.0.0.1:8000, fresh vehicle per scenario, 1 Hz telemetry.

| Scenario | samples | coolant max | oil max | battery min | load mean | Findings | Score/Status |
| -------- | ------- | ----------- | ------- | ----------- | --------- | -------- | ------------ |
| `high_temperature` (180 s) | 176 | **114.9** | 106.0 | 12.04 | 32.3 | `COOLANT_TEMP_HIGH` **critical**, `OIL_TEMP_HIGH` warning, 2× rapid-rise warning | **60 / attention** |
| `low_battery` (45 s) | 44 | 78.1 | 63.3 | **10.94** | 36.2 | `BATTERY_VOLTAGE_LOW` **warning**, `LOW_DATA_COVERAGE` info | **70 / attention** |
| `high_engine_load` (180 s) | 177 | 89.9 | 86.5 | 12.04 | **46.6** | `ENGINE_LOAD_HIGH` **warning** | **70 / attention** |
| `normal` (45 s) | 43 | 77.6 | 62.8 | 12.04 | 36.4 | `LOW_DATA_COVERAGE` info, warm-up rapid-rise warnings | **80 / healthy** |

Additionally, on the demo vehicle (which carries historical telemetry), a
hot-window analysis produced `coolant_temperature` baseline **"elevated"**
relative to its own history while a subsequent cooling window reported
**"depressed"** — verifying the per-vehicle baseline path end to end.

Every scenario's generated snapshot was immediately readable via
`GET /health` (latest) and `GET /health/history` (total grew 1→2→3→4).

---

## 11. Calibration observations (empirically confirmed)

- Coolant reaches ~115 °C only after sustained runtime (long warm-up); a 45-s
  run yields ~78 °C max. Warning/critical thresholds match measured behaviour
  after ≥ 180 s.
- Engine-load warning (mean>40%) fires with the load-multiplied cycle when
  cruising dominates the window (`SIMULATOR_CRUISING_SECONDS=50`);
  a 45-s run stays under the mean threshold — expected for the rule's mean-basis.
- Low-battery min dips to ~10.9 V (warning); critical requires < 10.5 V.
- Cold-start warm-up legitimately trips the rapid-rise rule (25 → 78 °C),
  which is why `normal` shows rapid-rise warnings but still **healthy**
  (info/warnings total penalty ≤ the healthy band).
- Subscriber processing jitter occasionally produces ~4 s gaps at burst load,
  correctly reported by `TELEMETRY_GAP` (info).

---

## 12. How to run the Phase 3 feature

```bash
alembic upgrade head                      # apply migration
uvicorn app.main:app --reload             # API
python -m app.mqtt.subscriber             # ingest MQTT
python -m scripts.seed_demo_vehicle       # demo vehicle (once)
$env:SIMULATOR_SCENARIO="high_temperature"   # any of the four scenarios
python -m simulator.main                  # let it run ≥ 3 min for temp/load

curl -X POST http://localhost:8000/api/v1/vehicles/11111111-2222-4333-8444-555555555555/health/analyze
curl http://localhost:8000/api/v1/vehicles/11111111-2222-4333-8444-555555555555/health
curl "http://localhost:8000/api/v1/vehicles/11111111-2222-4333-8444-555555555555/health/history"
```

---

## 13. Scope not covered / limitations

- **Docker runtime verification was not performed** because Docker is not
  installed on this machine; all verification used local Postgres, local
  Mosquitto and `uvicorn`.
- The `mqtt_e2e` sub-suite runs only with a live broker; it passed during
  Phase 2 verification but is deselected in the default CI run.
- `window_minutes` is bounded to 1–1440 per call; the engine expected-interval
  is a configurable estimate, not a learned per-vehicle cadence.
- The modern `opportunity/` vehicle rest-service calibration targets the
  simulator's physical values; thresholds remain fully configurable via
  `RuleThresholds`.

---

## 14. README

README updated with Phase 3 scope, architecture diagram, engine pipeline,
scoring/confidence explanation, endpoint + curl examples, migration notes,
test-suite description, and scenario→finding mapping (new §12 "Vehicle Health
Context", renumbered §11–§19).

---

## 15. Conclusion

Phase 3 satisfies the specification: deterministic, explainable, API-triggered
health analysis over historical telemetry; typed transport-agnostic engine;
rules/scoring/confidence with a documented method; immutable JSONB snapshots;
full toolchain of unit/integration/API tests; Alembic migration verified
up-down-up; live MQTT-to-analysis evidence for all four scenarios; all
Phase 1/2 functionality green. The phase is complete and ready for the LLM
reasoning layer (Phase 4) to consume `HealthContext` snapshots.