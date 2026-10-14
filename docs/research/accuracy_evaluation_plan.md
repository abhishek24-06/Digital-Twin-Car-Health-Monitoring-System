# Digital Twin — Accuracy & Fault-Detection Evaluation Plan

**Status:** PLAN (pre-registration) — no evaluation results exist yet.
**Created:** 2026-10-13
**Scope:** Evaluate the *existing* determinant health/fault/alert/AI pipeline of the
Digital Twin Car Health Monitoring Platform. This document is written **before**
any evaluation code or results, and its label mappings are frozen before the first
run so results cannot be tuned after the fact.
**Owner:** research evaluation workstream (uncommitted working tree).

> **Integrity contract.** No number in any result produced under this plan may be
> fabricated, back-filled from the system's own output, or described as real-world
> validation. Every reported quantity must carry one of four provenance tags:
> `MEASURED` (produced by executing the shipped code), `SIMULATED` (from generated
> synthetic telemetry), `MANUALLY_LABELLED` (human-assigned reference), or
> `UNVALIDATED` (claimed but not measured here). Anything that cannot be measured
> is reported as a limitation, not as a result.

---

## 1. System under test (inspected, read-only)

The evaluation targets the shipped code paths; **it does not modify the health
algorithm, thresholds, scoring, alert logic, or AI layer to improve any score.**

| Concern | Implementation (reference) |
| --- | --- |
| Deterministic analysis orchestration | `backend/app/intelligence/engine.py` → `HealthAnalysisEngine.analyze(...)` |
| Rules & thresholds | `backend/app/intelligence/rules.py` → `HealthRuleEngine`, `RuleThresholds` |
| Scoring / status / confidence | `backend/app/intelligence/scoring.py` |
| Statistics, trends, baselines | `backend/app/intelligence/{statistics,trends,baselines}.py` |
| Live current-session service | `backend/app/services/vehicle_health_service.py` → `analyze_live_vehicle(...)` |
| Alert materialization & lifecycle | `backend/app/services/alert_service.py` → `AlertService.sync_from_snapshot(...)` |
| Live alert monitor | `backend/app/services/health_monitor.py` |
| AI diagnosis workflow | `backend/app/agent/{service,graph,nodes,grounding,prompts}.py`, RAG in `backend/app/rag/` |
| Telemetry envelope & validation | `backend/app/mqtt/schemas.py` → `TelemetryMessage`, `TelemetryData` |
| Persistence | `backend/app/models/telemetry.py`, `backend/app/models/alert.py`, `.../health_snapshot.py` |
| Simulator (data generator) | `backend/simulator/{telemetry_generator,config,main}.py` |
| HTTP surface | `/api/v1/vehicles/{id}/health[/live|/analyze|/history]`, `.../alerts`, `.../agent`, `.../historical-analytics` |

### 1.1 Telemetry schema, units, sampling, validation

- Metrics and units (`models.py::METRIC_UNITS`): `rpm` (rpm, 0–10000),
  `speed` (km/h, 0–400), `engine_load` (%, 0–100), `coolant_temperature` (°C,
  −60…200), `oil_temperature` (°C, −60…200), `battery_voltage` (V, 0–40),
  `fuel_level` (%, 0–100), `intake_air_temperature` (°C, −60…120),
  `throttle_position` (%, 0–100), `engine_runtime` (s, ≥0), `odometer` (km, ≥0).
- Validation: MQTT `TelemetryMessage` forbids extra fields, requires a
  timezone-aware `timestamp`, a `schema_version` (1–255), a 1–64 char `event_id`,
  and a `vehicle_id`; `simulation_run_id` is optional.
- Sampling: expected interval `health_expected_interval_seconds = 1.0 s`
  (config default); simulator interval `SIMULATOR_INTERVAL_SECONDS = 1.0 s`.
- Idempotency: partial unique index on `(vehicle_id, source_event_id)`.

### 1.2 Deterministic fault rules (thresholds are code, not learned)

Rule ids / severities (from `RuleThresholds`):

| Rule id | Trigger (deterministic) | Severity | Category |
| --- | --- | --- | --- |
| `COOLANT_TEMP_HIGH` | window coolant `max > 110` (crit) / `> 100` (warn) | critical/warning | temperature |
| `OIL_TEMP_HIGH` | window oil `max > 110` (crit) / `> 100` (warn) | critical/warning | temperature |
| `BATTERY_VOLTAGE_LOW` | `min < 10.5` (crit) / `< 12.0` (warn) | critical/warning | electrical |
| `BATTERY_VOLTAGE_HIGH` | `max > 15.0` | warning | electrical |
| `ENGINE_LOAD_HIGH` | mean `> 60` (crit) / `> 40` (warn) | critical/warning | engine |
| `RPM_UNUSUAL` | mean `> 4500` | warning | engine |
| `FUEL_LEVEL_LOW` | `min < 5` (crit) / `< 15` (warn) | critical/warning | fuel |
| `RAPID_COOLANT_RISE` / `RAPID_OIL_TEMP_RISE` | `last − first ≥ 8 °C` (≥3 samples) | warning | temperature |
| `TELEMETRY_GAP` / `LOW_DATA_COVERAGE` | data-quality, `info` | info | data_quality |
| `INSUFFICIENT_DATA` / `LIMITED_DATA` / `LIVE_DATA_SUFFICIENCY` | data-sufficiency, `info` | info | data_quality |

### 1.3 Health score / status model

Start at 100; deduct **10 per warning** and **30 per critical** finding; penalties
are accumulated per category and each category is **capped** (see `scoring.py` for
the cap). Status mapping: `healthy` (score ≥ 90 — see `scoring.py`), `attention`,
`critical`; data-state labels `no_data` / `limited_data` are **provisional** and
carry `provisional_rating`. `confidence` is a **data-quality confidence**, *not* a
probability of a fault.

**Important:** the score is a deterministic function of the *same findings* the
rules emitted. It is therefore **not** an independent health reference.

### 1.4 Simulator fault-injection capability (existing, unmodified)

`ScenarioName ∈ {normal, high_temperature, low_battery, high_engine_load}`. A
scenario changes physical set-points only:

| Scenario | Physical modification | Intended observable |
| --- | --- | --- |
| `normal` | none | negative control (no alert-worthy finding expected) |
| `high_temperature` | coolant target 115 °C, oil target 108 °C | coolant (critical) / oil (warning) high |
| `low_battery` | running 11.9 V, offline 11.4 V | `BATTERY_VOLTAGE_LOW` (warning) |
| `high_engine_load` | load ×1.5 (clamped ≤100) | `ENGINE_LOAD_HIGH` when mean > 40 |

Generation is a seeded, deterministic state machine (`SIMULATOR_SEED`,
`random.Random`), so a given `(scenario, seed)` reproduces the exact sample
sequence. There is **no** per-sample fault label emitted by the simulator; the
label is the scenario we chose, recorded independently by the harness.

### 1.5 Live-session / run identity & history separation

- Every live analysis is scoped to one explicit `simulation_run_id`; only rows
  carrying that exact run id count as current-session evidence
  (`analyze_live_vehicle`). Historical rows are loaded through a separate
  baseline query and are never fused into current-run statistics.
- `GET /health/live` evaluates **without persisting**; the background monitor
  persists snapshots and is the only path that materializes alerts
  (`persist=True`).
- Historical (windowed) analyses **never** create alerts.

### 1.6 Alert lifecycle

- A live, non-provisional snapshot materializes one alert per alert-worthy
  **warning/critical** finding. Deduplication key is `"{vehicle_id}:{rule_id}"`;
  repeats increment `occurrence_count` and append a `RECURRED` event (no new
  alert). A definitive evaluation that no longer observes a condition
  **auto-resolves** it. Data-quality / data-sufficiency findings are excluded.
- Alerts are only created from `current_session` evidence, never from a
  historical window.

### 1.7 AI diagnosis

LangGraph workflow: `VehicleContextTool` (reads the deterministic health context)
→ optional RAG `ManufacturerGuidanceTool` → LLM → grounding/validation →
`DiagnosisResponse`. Evidence must trace to real findings/metrics; unsupported
items are dropped. A deterministic `mock` provider exists (`llm_*_provider="mock"`).
The RAG path needs a pgvector-capable database (absorbs a local `retrieval-error`
when absent).

### 1.8 Existing tests / datasets / timing signals

- Unit/integration suites exist under `backend/tests/**` incl. a real-DB
  full-system acceptance test (`tests/acceptance/test_full_system_acceptance.py`).
- **No labelled telemetry dataset and no expert reference diagnoses exist in the
  repository.** This is the central limitation of the whole evaluation.
- The engine records `analysis_duration_ms` (internal compute latency) and the
  interpreter logs per-analysis fields; telemetry rows carry `created_at`.

---

## 2. Output taxonomy — predictions vs. references vs. system labels

This distinction governs every metric choice below.

| Output | Kind | Independent of the algorithm? |
| --- | --- | --- |
| `findings[].rule_id/severity` | **prediction** (deterministic rule output) | no |
| `health_score` | **system label** (function of the same findings) | no |
| `health_status` | **system label** (score bucket) | no |
| `confidence` | **data-quality label** (not fault probability) | partially |
| `alerts[]` | **system label** (materialized from findings) | no |
| `DiagnosisResponse` | **prediction** (LLM/mock interpretation) | no |
| injected scenario / fault episode | **reference** (chosen by the harness) | **yes** |
| expert diagnosis | **reference** (does not exist here) | yes (if it existed) |

**Rule:** only the *reference* column may be used as ground truth. The system's own
outputs may never be used to label the data they are scored against.

---

## 3. Research questions and evaluability (decided up front)

| RQ | Question | Evaluability on this system | Why |
| --- | --- | --- | --- |
| RQ1 | Detect independently-labelled faults | **SIMULATED, measurable** | injected scenarios are known; detection is an episode-level classification |
| RQ2 | Health assessment vs. independent reference | **SIMULATED, partially measurable — no absolute reference** | no independent health scale exists; only ordinal "anomaly vs. normal" discrimination is defensible |
| RQ3 | Alert FP / missed / duplicates | **SIMULATED, measurable** | real `AlertService` driven by real engine snapshots against known episodes |
| RQ4 | Telemetry → detection/alert latency | **MEASURED (software pipeline)** | timestamps captured by the harness; on a single host |
| RQ5 | AI diagnosis correctness | **NOT EVALUABLE for correctness; grounding contract measurable** | no expert-labelled reference diagnoses; mock provider has no language quality |
| RQ6 | Robustness to duplicate/malformed/out-of-order/delayed data | **SIMULATED + MEASURED, measurable** | real MQTT + DB persistence paths (extends the Phase C harness) |

Every RQ result will state its evaluability status verbatim. RQ2 and RQ5 will
**not** be reported as "accuracy".

---

## 4. Ground truth & dataset strategy

### 4.1 Dataset: `synthetic-scenarios-v1` (SIMULATED)

Generated by the harness, not hand-edited:

- Unit of evaluation = a **fault episode**: one `(scenario, seed, duration)` run of
  the real `SimulationEngine`, emitting telemetry at 1 Hz.
- Episode duration ≥ 180 s at 1 Hz so each scenario reaches its physical
  set-point (the state machine warms up through OFF→STARTING→IDLE→
  ACCELERATING→CRUISING→DECELERATING).
- Episodes: `normal` (negative control), `high_temperature`, `low_battery`,
  `high_engine_load`, across ≥ 5 seeds each.
- Every generated sample is stored with provenance:
  `dataset_id, episode_id, scenario, seed, run_id, t, values{...}` plus episode
  metadata `expected_family`, `expected_rule_ids`, `label_source =
  "harness-injected-scenario"`, `provenance = SIMULATED`, `label_version`.

Because the simulator *is* the generator, this is **not** real-world validation.
It measures whether the deterministic pipeline detects the physical conditions it
was explicitly configured to detect. Reported as `SIMULATED` only.

### 4.1.1 Two pre-registered analysis views (warm-up control)

A physically normal warm-up *is itself* a rapid temperature rise, and the engine
has rapid-rise rules. To avoid conflating warm-up transients with fault
detection, every episode is analysed in **both** of these views, fixed now:

- **`full`** — analyse the whole episode window (0…180 s), including warm-up.
  This is the **warm-up-sensitivity / false-positive** view.
- **`steady`** — analyse only the steady-state suffix (the last 60 s, 120…180 s).
  This is the **primary fault-detection** view.

All headline detection/health metrics use the `steady` view; the `full` view is
reported alongside. Pre-registered warm-up prediction: a normal cold start ramps
coolant/oil from ambient to operating temperature, which trips
`RAPID_COOLANT_RISE` / `RAPID_OIL_TEMP_RISE` in **every** scenario, including the
`normal` control. Those are counted as **false positives for the negative control
and reported, never suppressed**. Because a warm-up rapid-rise finding is
`thermal`, the `full` view is expected to misclassify `low_battery` episodes as
`thermal`; that is a genuine property of the shipped rules and is reported as
such rather than hidden.

### 4.2 Pre-registered label mapping (frozen before the first run)

**Reference label = injected scenario family** (independent of the algorithm):

`normal → none`, `high_temperature → thermal`, `low_battery` → electrical`,
`high_engine_load` → engine_load.

**Predicted class** = aggregation of produced alert-worthy `rule_id`s via this
fixed, documented mapping (NOT tuned against results):

| Predicted family | rule ids |
| --- | --- |
| `thermal` | `COOLANT_TEMP_HIGH`, `OIL_TEMP_HIGH`, `RAPID_COOLANT_RISE`, `RAPID_OIL_TEMP_RISE` |
| `electrical` | `BATTERY_VOLTAGE_LOW`, `BATTERY_VOLTAGE_HIGH` |
| `engine_load` | `ENGINE_LOAD_HIGH` |
| `engine_speed` | `RPM_UNUSUAL` |
| `fuel` | `FUEL_LEVEL_LOW` |

Episode prediction = the family (or families) appearing among alert-worthy
findings; the **primary** family is the highest-severity family, ties broken by the
pre-registered order `thermal > electrical > engine_load > engine_speed > fuel`.
`normal` episodes predict `none`.

**Circularity control.** Expected condition is derived from the *injected physical
state* (e.g. "coolant is driven to 115 °C"), chosen with a deliberate margin above
the threshold so classification does not hinge on threshold coincidence. Both the
injection magnitudes and this mapping are frozen before the first run; the normal
control measures false positives.

### 4.2.1 Manual reference set (optional, MANUALLY_LABELLED)

If (and only if) a human reviewer authors reference diagnoses/labels, they go in a
separate registry tagged `MANUALLY_LABELLED` with reviewer identity and date. **The
agent will not author reference labels on the system's behalf.** If none are
produced, RQ5 correctness stays `NOT EVALUABLE`.

### 4.3 Provenance record (required per dataset/artifact)

`dataset_id`, `generator` (code path + seed), `reference_source`, `label_method`,
`created_at`, `code_revision`, `limitations[]`. No result is published without it.

---

## 5. Experimental protocol

1. **Freeze.** Record this plan + a content hash and the code revision in the
   results directory. Label mappings and metrics are frozen here.
2. **Generate** `synthetic-scenarios-v1` deterministically (fixed seeds).
3. **Analyze** each episode by calling the real `HealthAnalysisEngine` on the
   episode's window (and, for live metrics, `VehicleHealthService.analyze_live_vehicle`
   against an isolated disposable DB). The engine is imported, never copied.
4. **Alert evaluation** feeds the engine's real non-provisional snapshots into the
   real `AlertService.sync_from_snapshot` in episode order inside an isolated
   disposable database.
5. **Latency** is captured by the harness (publish timestamp vs. persistence
   timestamp), not by trusting internal log lines.
6. **Emit** JSON + Markdown with per-episode records and aggregate metrics.
7. **Repeat** across all seeds; report mean and spread (min/max or stdev), never a
   single cherry-picked seed.

**Isolation is mandatory** (mirrors the Phase C harness): a dedicated disposable
database name, loopback only, fail-closed (`RuntimeError`) if the target is not
verifiably isolated (`supabase`/`pooler`/`amazonaws`/`render.com`/`neon.tech`
markers or a non-test name). Never point evaluation at hosted/production data.

### 5.1 Pre-registered matching rules (alerts)

- **Episode window:** `[onset, end]` (from the harness clock).
- **Match:** an alert matches an episode iff `alert.rule_id ∈ expected_rule_ids(episode)`
  **and** `alert.first_seen_at ∈ [onset − 0 s, end + W]`, with match tolerance
  **`W = 0 s`** for the deterministic snapshot-fed harness (the evaluation is fed
  at deterministic points, so no propagation delay is implied).
- **Detection (RQ1):** an episode is a *hit* iff a finding with a rule in its
  `expected_rule_ids` and severity ≥ expected severity appears in its analysis.
- Unresolved alerts and episodes with an incomplete observation window are
  reported **separately**, never folded into recall.

---

## 6. Metrics (definitions fixed here)

### RQ1 — fault detection (SIMULATED)
Per fault family over episodes: confusion counts `TP/FP/FN/TN`, **precision,
recall, F1, accuracy**; macro-F1 and (if class sizes differ) weighted-F1; the full
confusion matrix; per-family support; and a **negative-control false-positive
count** from `normal` episodes. Also report **severity agreement** (predicted vs.
expected max severity) as an ordinal confusion.

### RQ2 — health assessment (SIMULATED, ordinal only)
- **No regression metrics** (MAE/RMSE/R²) are computed: there is no independent
  numeric health reference; computing them against a fabricated or self-generated
  value is prohibited by the integrity contract.
- **Ordinal discrimination (primary):** ROC-AUC of `health_score` separating
  `normal` vs. `any-fault-injected` episodes, and `normal` vs. the
  `critical-expected` family, with the injected condition as reference. Report AUC
  with the number of episodes; do **not** call AUC "accuracy".
- **Descriptive:** distribution of `health_status` per injected family, explicitly
  flagged as **partly circular** because status buckets and rules share thresholds.
- The health-score scale, reference source (`injected fault presence`) and
  evaluation unit (per episode) are stated with every number.

### RQ3 — alert quality (SIMULATED)
Alert precision/recall (per §5.1 rules), **false alarms per vehicle-hour**
(`FP alerts ÷ exposure hours`), missed episodes, **duplicate alerts per episode**
(distinct `Alert` rows minus 1; expected 0 due to dedup), **time-to-first-detection**
(`first_seen_at − onset`), **time-to-resolution** (`resolved_at − recovery`) for
episodes that recover, with unresolved alerts reported separately.

### RQ4 — latency (MEASURED, software pipeline)
- **Compute latency:** `analysis_duration_ms` (p50/p95/p99).
- **Ingest latency:** publish `timestamp` → telemetry row `created_at`.
- **Detection/alert latency:** publish `timestamp` → alert `first_seen_at`.
- Reported as p50/p95 with sample counts. Explicitly labelled *software pipeline
  latency on one host*, not a physical control-loop latency. Clock is single-host
  monotonic; no cross-host skew claim is made.

### RQ5 — AI diagnosis (NOT EVALUABLE for correctness)
- **Not measured:** top-1 / top-k diagnosis accuracy, category P/R/F1, because no
  expert-labelled reference diagnoses exist. Stated as a limitation, not a result.
- **Measurable grounding contract** (with the deterministic mock provider): rate of
  `evidence` items that resolve to a real finding/metric in the context
  (`grounding rate`); rate of cited sources that resolve to retrieved evidence;
  schema completeness; and whether the diagnosis is deterministic for a fixed
  context. These are **system-contract** measures, never "diagnostic accuracy".

### RQ6 — robustness (SIMULATED + MEASURED)
Under duplicate delivery, delayed/out-of-order arrival, dropped/malformed messages
and broker restart: retained detection rate vs. the clean baseline, induced false
positives, persistence integrity (no lost/duplicated rows), and ordering validity.
Reported as deltas from the clean control, with the exact fault-injection method.

---

## 7. Data-leakage risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Using the system's predictions as ground truth | Only harness-injected scenario/fault presence is a label (§4.1) |
| Tuning labels/metrics to raise the score | Mappings + metrics frozen and hashed before the first run (§5.1) |
| Same seed for "fit" and "evaluation" | There is no fitting; still, evaluate over multiple seeds and report spread |
| Baseline window contaminated by the fault | Dedicated baseline half / `exclude_run_id`; report when baseline is intentionally disabled |
| Live vs. historical confusion | All alert/latency metrics use the `current_session` path only |
| Duplicate `event_id` masking lost data | Track unique-constraint hits; measure delivered vs. persisted counts |
| Circular severity reference | Injection margins exceed thresholds; negative control; circularity flagged explicitly for RQ2 status buckets |
| Silent fallback making a failure look healthy | Harness fails closed; any degraded subsystem is reported, never masked |

---

## 8. Limitations & threats to validity (to be repeated in every report)

1. **Synthetic only.** No real-vehicle, real-fault, or public labelled dataset is
   present; results are *simulated* and do not establish real-world accuracy.
2. **No independent health scale.** RQ2 is ordinal discrimination only.
3. **No expert diagnoses.** RQ5 correctness is unmeasurable; only grounding is.
4. **Deterministic rules.** The system is not a learned classifier; "accuracy"
   means agreement with injected conditions, not statistical generalization.
5. **Single-host latency.** No network/physical transport latency is measured.
6. **Scenario coverage.** Only four scenarios / rule families exist; uncovered
   rules (e.g. `RPM_UNUSUAL`, `FUEL_LEVEL_LOW`) have no injected positive control
   and will be reported as such.
7. **Environment.** Local PostgreSQL without pgvector; RAG may degrade with
   `rag_reason="retrieval-error"`.

---

## 9. Evaluation infrastructure (planned; not yet implemented)

Package `backend/evaluation/` (standalone; **must not** import test-only shims or
modify shipped code):

- `registry.py` — dataset/episode schemas + provenance validation.
- `scenarios.py` — deterministic generation of `synthetic-scenarios-v1` reusing
  `simulator.telemetry_generator.SimulationEngine`.
- `runner.py` — run the real `HealthAnalysisEngine` over episodes; emit per-episode
  predictions.
- `metrics/{detection,health,alerts,latency,diagnosis}.py` — the §6 metrics.
- `report.py` — JSON + Markdown emitters with the provenance header and per-RQ
  status tags (`MEASURED` / `SIMULATED` / `MANUALLY_LABELLED` / `UNVALIDATED`).
- `cli.py` / `__main__.py` — `python -m evaluation ...`.

Alert + latency evaluation reuse the isolated-DB, fail-closed pattern from the
Phase C MQTT harness (`backend/tests/mqtt/conftest.py` /
`backend/scripts/run_mqtt_integration.py`) with a dedicated disposable DB name.

Tests `backend/tests/evaluation/` (hermetic, no DB, no broker) verify: metric math
on hand-computed fixtures, episode determinism, provenance enforcement, and that
the runner calls the real engine.

Results live under `docs/research/results/<dataset_id>/` with `provenance.json`,
`metrics.json`, and `REPORT.md`.

**Commands (planned):**
```
python -m evaluation generate --dataset synthetic-scenarios-v1 --seeds 5
python -m evaluation analyze  --dataset synthetic-scenarios-v1
python -m evaluation alerts   --database <isolated disposable DB>   # fail-closed
```

---

## 10. Reporting format & status separation

Every report separates:

- **What was executed** (command, exit code, environment).
- **What was measured** vs. **simulated** vs. **manually labelled** vs.
  **unvalidated**.
- **Per-RQ verdict** using the §3 evaluability status (including the explicit
  NOT-EVALUABLE verdicts for RQ2-absolute and RQ5-correctness).
- **Limitations** (§8) and **incomplete observation windows** / **unresolved
  alerts** separately from completed ones.

---

## 11. Pre-registration checklist (all required before any result is final)

- [ ] This plan committed to the results directory with a content hash.
- [ ] Code revision recorded.
- [ ] Label mappings (§4.1, §4.2) frozen and hashed.
- [ ] Matching rules (§5.1) frozen and hashed.
- [ ] Metric definitions (§6) frozen and hashed.
- [ ] Isolated evaluation DB name chosen and fail-closed guard tested.
- [ ] `normal` negative control included in every run.
- [ ] Multiple seeds scheduled; spread reporting enabled.
- [ ] RQ5 correctness and RQ2-absolute explicitly marked NOT EVALUABLE unless a
      human-labelled reference is supplied.

---

## 12. Explicitly out of scope

- Changing the health algorithm, thresholds, scoring, alert logic or prompts.
- Weakening auth, data isolation, live-session isolation, alert lifecycle or
  telemetry integrity.
- Committing, pushing, deploying, restarting services, changing secrets, or
  migrating any hosted database.
- Reporting any real-world accuracy claim from synthetic data.

---

## 13. Implementation status (appended after first run)

**Do not confuse this section with the pre-registration above.** The
pre-registration (§§1–12) was written before implementation; this section records
what has actually been built and executed.

### Implemented and executed

| RQ | Status | Evidence |
| --- | --- | --- |
| RQ1 fault detection | **SIMULATED — executed** | `docs/research/results/synthetic-scenarios-v1/REPORT.md`; steady-view accuracy 1.000 over 20 episodes (4 scenarios × 5 seeds) |
| RQ2 health discrimination | **SIMULATED — executed (ordinal only)** | AUC 1.000; no regression metrics by design |
| RQ4 compute latency | **MEASURED — executed (compute only)** | `analysis_duration_ms` p50 ≈ 1.4 ms |
| RQ5 AI-diagnosis grounding | **metric implemented; correctness NOT EVALUABLE** | `backend/evaluation/metrics/diagnosis.py` + `tests/evaluation/test_diagnosis.py` |

Code: `backend/evaluation/**`; tests: `backend/tests/evaluation/**` (22 passed).
Frozen content hashes: `docs/research/results/synthetic-scenarios-v1/PLAN_HASHES.json`.

### Implemented but NOT executed (reported as limitations, not results)

| RQ | Status | Blocker |
| --- | --- | --- |
| RQ3 alert FP / miss / duplicates / latency | **not executed** | requires driving the real `AlertService.sync_from_snapshot` against an isolated disposable DB |
| RQ4 pipeline latency (publish→persist→alert) | **not executed** | requires the isolated MQTT + DB harness |
| RQ6 robustness (duplicate / malformed / out-of-order / delayed) | **not executed** | harness not yet built |

### Findings that must accompany any citation of the numbers

1. The `normal` negative control produced alert-worthy warm-up findings
   (`RAPID_COOLANT_RISE`, `RAPID_OIL_TEMP_RISE`) in **5/5** full-window episodes.
   Any alert materialized from those findings would be a cold-start false
   positive. (No health-algorithm change is proposed here — out of scope.)
2. Warning-only faults (low battery, high engine load) map to
   `health_status = healthy` (score 90) under the shipped scoring, while a
   critical+warning fault maps to `attention` (60). This is descriptive and
   partly circular (§6 RQ2).
3. RQ1's 1.000 steady-view accuracy reflects deterministic rules firing on the
   exact conditions they were written for, on synthetic data — it is **not**
   evidence of real-world generalization.

### Pre-registration checklist (status as of this run)

- [x] Plan recorded with content hashes (`PLAN_HASHES.json`) — commit is out of
      scope for this workstream.
- [x] Code revision recorded (`66674bd`).
- [x] Label mappings frozen and hashed.
- [x] Matching rules (§5.1) frozen and hashed (execution of RQ3 pending).
- [x] Metric definitions frozen and hashed.
- [ ] Isolated evaluation DB name chosen and fail-closed guard tested (RQ3).
- [x] `normal` negative control in every run.
- [x] Multiple seeds (5) with spread reporting.
- [x] RQ5 correctness and RQ2-absolute marked NOT EVALUABLE.
