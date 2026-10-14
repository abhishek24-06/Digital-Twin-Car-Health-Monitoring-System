# Digital Twin — Fault-Detection, Alert, Latency & Robustness Evaluation

**Final engineering report (10 sections).**
**Date:** 2026-10-13 · **Branch:** `main` (all work uncommitted) · **Code revision:** `66674bd`

> **Integrity contract.** Every quantity below carries a provenance tag:
> `MEASURED` (produced by executing the shipped code), `SIMULATED` (synthetic
> telemetry, injected reference), `MANUALLY_LABELLED` (human reference — none
> exist), or `NOT EVALUABLE`. Nothing is fabricated, back-filled from the
> system's own output, or presented as real-world validation. Where a metric
> cannot be computed honestly it is reported as a limitation, not a number.
> The shipped analyzer (`app/intelligence/{engine,rules,scoring,models}.py`) was
> never modified.

**Artifacts this report draws from**

| Result set | Contents | RQs |
| --- | --- | --- |
| `docs/research/results/synthetic-scenarios-v2/` | 20 episodes × 2 analysis views; per-episode classification & health | RQ1, RQ2, RQ4-compute |
| `docs/research/results/synthetic-pipeline-v1/` | Live alert lifecycle, wall-clock latency, injected-fault robustness | RQ3, RQ4-pipeline, RQ6 |
| `docs/research/accuracy_evaluation_plan.md` | Frozen pre-registration (label mappings, matching rule `W = 0 s`, metric definitions) | protocol |

---

## 1. Executive summary

The Digital Twin's deterministic health pipeline was evaluated against
harness-injected fault scenarios on synthetic telemetry, plus real MQTT → Postgres
→ alert service behaviour on a disposable database and a private broker.

- **RQ1 fault detection — SIMULATED, measured.** On the pre-registered `steady`
  view, per-family accuracy / macro-F1 / weighted-F1 are **1.000** over 20
  episodes (4 scenarios × 5 seeds); the `normal` negative control raised **0**
  alert-worthy findings. On the `full` (warm-up-inclusive) view, accuracy falls
  to **0.250** because ordinary cold-start warm-up trips `RAPID_COOLANT_RISE` /
  `RAPID_OIL_TEMP_RISE` in every episode, including the control. *This is a
  property of the shipped rules, reported rather than suppressed.*
- **RQ2 health assessment — SIMULATED, ordinal only.** ROC-AUC for separating
  injected-anomaly vs. normal is **1.000**. **No regression metrics** (MAE/RMSE/R²)
  are reported: no independent continuous health reference exists. The status
  confusion is **partly circular** (status buckets and rules share thresholds) and
  is labelled as such.
- **RQ3 alert lifecycle — SIMULATED episodes / MEASURED alerts.** Driving the real
  `VehicleHealthService.analyze_live_vehicle` → `AlertService.sync_from_snapshot`
  over 12 replayed episodes: episode recall **100% (9/9)**, episode precision
  **75.0%**, expected-rule recall **100%** (12/12), alert precision **33.3%**
  (12/36). **0 duplicate alert rows**; false alarms **40 / vehicle-hour**
  (all of it cold-start `RAPID_*` transients). Time-to-first-detection p50
  **22 s** (n=9; p95 not justified). Every snapshot fed to the alert service was
  `current_session` (2160/2160).
- **RQ3 recovery — SIMULATED.** Every injected fault rule auto-resolved after a
  condition-free session: TTR **30 s** for all 4 resolved fault rules, which is
  exactly the engine's 30-sample definitive threshold.
- **RQ4 latency — MEASURED (single host, monotonic).** publish→persisted row
  p50 **3.9 ms** / p95 6.8 ms; engine self-reported analyse p50 **1.2 ms**;
  full monitor pass (analyse + alert sync) p50 **16.1 ms** / p95 22.9 ms;
  publish→alert p50 **21.8 ms** (n=9, only the median is justified). 0 monitor
  failures in 180 samples.
- **RQ5 AI-diagnosis correctness — NOT EVALUABLE.** No expert-labelled reference
  diagnoses exist. Only the grounding contract is measurable; it is not accuracy.
- **RQ6 robustness — MEASURED/SIMULATED.** 10/10 injected-fault cases passed:
  duplicate idempotency, repeated ids across flushes, out-of-order arrival,
  delayed messages, a data gap, malformed/schema-invalid payloads, unknown
  vehicles, a transient database failure with subscriber retry, and a mid-stream
  broker restart with reconnect. No lost or duplicated rows beyond the injected
  faults.

**Bottom line.** The pipeline is correct and predictable on the conditions it was
built to detect, and it degrades safely under the fault classes tested. The
system's one systematic weakness is **cold-start false positives** from the
rapid-rise rules, which is visible only in the warm-up-inclusive view and in the
per-episode alert counts. None of this establishes real-world accuracy; the
reference is the injected scenario, not an independent sensor.

---

## 2. System under test (inspected read-only)

| Concern | Implementation |
| --- | --- |
| Deterministic analysis | `backend/app/intelligence/engine.py` → `HealthAnalysisEngine.analyze` |
| Rules / thresholds | `backend/app/intelligence/rules.py` → `HealthRuleEngine`, `RuleThresholds` |
| Scoring / status | `backend/app/intelligence/scoring.py` |
| Live current-session service | `backend/app/services/vehicle_health_service.py` → `analyze_live_vehicle` |
| Alert materialization | `backend/app/services/alert_service.py` → `AlertService.sync_from_snapshot` |
| Live alert monitor | `backend/app/services/health_monitor.py` |
| Ingestion / validation | `backend/app/mqtt/{subscriber,schemas}.py` (`TelemetryMessage`, `TelemetryData`) |
| Persistence | `backend/app/models/{telemetry,alert,health_snapshot}.py` |
| Data generator | `backend/simulator/telemetry_generator.SimulationEngine` (unmodified) |

The analyzer is **deterministic rule logic, not a learned classifier**; "accuracy"
means agreement with injected physical conditions, not statistical
generalization. Four fault scenarios exist (`normal`, `high_temperature`,
`low_battery`, `high_engine_load`); rules without an injected positive control
(`RPM_UNUSUAL`, `FUEL_LEVEL_LOW`) cannot be validated here and are reported as
uncovered.

---

## 3. Methodology, isolation & integrity controls

**Reference labels are independent of the algorithm.** The reference is the
scenario the harness injected; the system's own outputs (findings, score, status,
alerts, diagnosis) are never used to label the data they are scored against.

**Two frozen analysis views** (fixed before the first run, plan §4.1.1):

- `steady` — the last 60 s of each 180 s episode (primary fault-detection view);
- `full` — the whole window, including warm-up (warm-up-sensitivity view).

**Alert matching (frozen, `W = 0 s`).** An alert matches an episode iff
`alert.rule_id ∈ expected_rule_ids` **and**
`alert.first_seen_at ∈ [onset, end]`.

**Real components, disposable infrastructure.** RQ3/RQ4/RQ6 drive the *shipped*
`VehicleHealthService.analyze_live_vehicle` and `AlertService.sync_from_snapshot`
against a dedicated disposable PostgreSQL database (`digital_twin_eval_test`) and
a private Mosquitto broker on a free loopback port with `persistence false`. A
**fail-closed** guard refuses any non-loopback host or a differently named
database before a single row is written; if the broker or database is unavailable
the run is recorded `NOT EXECUTED` with the blocker, never a fabricated result.

**Clock semantics.** RQ3 replays each episode on its synthetic clock
(`generated_at = point.timestamp`); recovery uses a second, condition-free `normal`
session on the same vehicle with the clock shifted +1 day; RQ4 is a *separate*
wall-clock streaming run (`generated_at=None`) timing publish→persist with a
monotonic clock. These are recorded in each run's `environment.clock_semantics`.

**Single-source reporting.** `REPORT.md` is rendered **strictly from the bytes of
`metrics.json`**; the renderer computes no measurement of its own, so report and
JSON cannot disagree. The frozen protocol + analyzer files are hashed into
`PLAN_HASHES.json`, and the runner refuses to overwrite a result set whose hashes
no longer match the working tree.

---

## 4. RQ1 — Fault detection (SIMULATED)

*Source: `synthetic-scenarios-v2`, 20 episodes (4 scenarios × 5 seeds).*

| View | accuracy | macro-F1 | weighted-F1 |
| --- | --- | --- | --- |
| `steady` (**primary**) | 1.000 | 1.000 | 1.000 |
| `full` (warm-up included) | 0.250 | 0.100 | 0.100 |

`steady` per-episode expected-rule detection:

| scenario | reference | episodes | detected expected | false-positive episodes |
| --- | --- | --- | --- | --- |
| normal | none | 5 | 0 | 0 |
| high_temperature | thermal | 5 | 5 | 0 |
| low_battery | electrical | 5 | 5 | 0 |
| high_engine_load | engine_load | 5 | 5 | 0 |

**`full` view — the honest negative result.** The `normal` control raised
`RAPID_COOLANT_RISE` and `RAPID_OIL_TEMP_RISE` in **5/5** episodes (ordinary cold
start from ambient to operating temperature is itself a rapid rise), which also
misclassifies every `low_battery` / `high_engine_load` episode as `thermal` in
that view. This is counted as false positives and reported, not suppressed.
Rules without an injected positive control (`RPM_UNUSUAL`, `FUEL_LEVEL_LOW`) are
not validated here.

---

## 5. RQ2 — Health assessment (SIMULATED, ordinal only)

*Source: `synthetic-scenarios-v2`.*

- **No regression metrics are computed.** There is no independent continuous
  health reference, so MAE/RMSE/R² are intentionally not reported; doing so
  against a self-generated value would violate the integrity contract.
- **Ordinal discrimination (primary):** AUC(`anomaly` vs `normal`) = **1.000**
  (n_anomaly = 15, n_normal = 5); AUC(`thermal` vs `non-thermal`) = **1.000**.
  AUC is discrimination, **not** accuracy.
- **Descriptive, partly circular** score/status behaviour (status buckets and
  rules share thresholds):

| view | family | n | health_score (min=median=max) | status |
| --- | --- | --- | --- | --- |
| steady | none | 5 | 100 | healthy |
| steady | thermal | 5 | 60 | attention |
| steady | electrical | 5 | 90 | healthy |
| steady | engine_load | 5 | 90 | healthy |
| full | none | 5 | 80 | healthy |
| full | thermal | 5 | 60 | attention |
| full | electrical | 5 | 70 | attention |
| full | engine_load | 5 | 70 | attention |

`health_status` is a function of the same findings the rules emitted, so it is
**not** an independent health reference; `confidence` is a data-quality measure,
not a fault probability.

---

## 6. RQ3 — Alert lifecycle (SIMULATED episodes / MEASURED alerts)

*Source: `synthetic-pipeline-v1`. The real monitor pair was driven per sample:
`VehicleHealthService.analyze_live_vehicle(generated_at=point.timestamp)` →
`AlertService.sync_from_snapshot(snapshot)`.*

| Metric | Value |
| --- | --- |
| Episodes | 12 (9 fault, 3 control); exposure 0.600 vehicle-hours |
| Episode recall | **100%** (9/9) |
| Episode precision | **75%** (3 control episodes predicted positive — all cold-start FPs) |
| Expected-rule recall | **100%** (12/12 episode-rule pairs) |
| Alerts | 36 total = 12 matching + 24 false positive; precision **33.3%** |
| False alarms | **40.0 per vehicle-hour** |
| Duplicate alert rows | **0**; recurrence-folded updates 5752 |
| Alerts provisional at creation | 30 (definitive at creation: 6) |
| Time to first detection | n=9, min 1 s, **p50 22 s**, max 46 s (p95/p99 not justified) |
| Unresolved within-episode | 36 (a single fault episode cannot self-resolve — see recovery) |
| Snapshot scope | `current_session` 2160 / 2160 (no historical scope) |

**Reading the false positives honestly.** All 24 FPs are the rapid-rise pair:
2 per control episode (3×2 = 6) and 2 per fault episode (9×2 = 18). They are
created because the live path evaluates the current session *including* its
warm-up ramp — the same phenomenon the `full` view exposes. Detection of the
*expected* rule was 100%, so the FPs are additive noise, not misses.

**Recovery (time to resolution, SIMULATED).** After each fault episode, a
condition-free `normal` session ran on the same vehicle; the first definitive
pass that no longer observed the rule auto-resolved it. All 4 resolved fault
rules gave **TTR = 30 s** — exactly the engine's 30-sample/30 s definitive
threshold. Recovery is modelled with a second session because one fault episode
cannot self-resolve; this is a protocol limitation, not a system property.

---

## 7. RQ4 — Pipeline latency (MEASURED, single host, monotonic clock)

*Source: `synthetic-pipeline-v1`, a separate wall-clock run (high_temperature,
seeds 1–3, 60 s at 1 Hz → 180 samples); publish→persist timed with a monotonic
clock; 0 monitor failures.*

| Stage | n | min | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- |
| publish → persisted telemetry row | 180 | 2.5 | **3.9** | 6.8 | 7.8 | 8.3 |
| engine self-reported analyse | 180 | 0.35 | **1.2** | 2.0 | 2.7 | 3.1 |
| monitor pass (analyse + alert sync) | 180 | 7.4 | **16.1** | 22.9 | 26.8 | 32.9 |
| publish → alert persisted | 9 | 17.9 | **21.8** | n/a† | n/a† | 54.3 |

All values in milliseconds. † `publish → alert` has only 9 samples, so p95/p99 are
**not justified**; only the median is reported. `publish → detection` and
`publish → alert` are the same instant here: a finding is materialised into a
persisted alert synchronously within the same monitor pass.

**Scope.** This is host-local software latency (MQTT subscriber → Postgres →
analyzer → alert row) with no external network or physical transport. It is not
control-loop latency.

Compute latency measured independently by the accuracy harness
(`analysis_duration_ms` per episode analysis, `synthetic-scenarios-v2`):
`steady` p50 **1.40 ms**, `full` p50 **3.70 ms** — consistent with the streaming
run's engine figure.

---

## 8. RQ5 — AI diagnosis (NOT EVALUABLE for correctness)

No expert-labelled reference diagnoses exist in the repository, and the agent will
not author reference labels on the system's behalf. Diagnostic **correctness** is
therefore **NOT EVALUABLE** and no accuracy-style number is reported.

The only defensible quantity is the **grounding contract** (does evidence trace to
real findings/metrics; are unsupported items dropped) using the deterministic
`mock` provider, implemented in `backend/evaluation/metrics/diagnosis.py` and its
tests. Grounding is a property of the plumbing, **not** diagnostic accuracy and
must never be cited as such. If a human reviewer authors a reference set tagged
`MANUALLY_LABELLED` (reviewer + date), RQ5 correctness could be evaluated later.

---

## 9. RQ6 — Robustness under injected delivery / DB / broker faults

*Source: `synthetic-pipeline-v1`. Faults injected into the live
MQTT → subscriber → Postgres path against a disposable database.*

| Case | Injected fault | Persisted | Expected | Pass |
| --- | --- | --- | --- | --- |
| `clean_baseline` | 5 distinct valid samples, once each | 5 | 5 | ✅ |
| `duplicate_delivery` | same `(vehicle,event_id)` delivered 5× | 1 | 1 | ✅ |
| `repeated_event_ids` | ids `[a,b,a,b]` across separate flushes | 2 | 2 | ✅ |
| `out_of_order` | arrival `[3,1,2,0]`, timestamps 0..3 | 4 | 4 | ✅ |
| `delayed_message` | one sample stamped 42 min in the past | 2 | 2 | ✅ |
| `missing_interval` | samples at −30,−29,−28,−1 s (27 s gap) | 4 | 4 | ✅ |
| `malformed_payloads` | 8 invalid envelopes, then 1 valid | 1 | 1 | ✅ |
| `unknown_vehicle` | valid envelope for an unregistered vehicle | 1 | 1 | ✅ |
| `transient_db_failure` | first 2 session acquisitions raise `DatabaseError` | 4 | 4 | ✅ |
| `broker_restart` | broker killed + relaunched mid-stream | 7 | ≥4 | ✅ |

Observations: duplicate delivery is **idempotent** on the partial unique index
`(vehicle_id, source_event_id)`; dedup holds **across** flush batches; stored
timestamps remain sorted and the **source timestamp is preserved** (not
overwritten with arrival time); malformed/schema-invalid payloads (empty, bad
JSON, non-object, missing fields, extra fields, `throttle_position=150`,
naive timestamp, `schema_version=0`) are **discarded** and the stream survives to
persist the next valid message; unknown vehicles persist **0** rows; the
subscriber retries through a transient DB failure (`session-factory calls: 6`) and
**reconnected 1.6 s** after a broker restart. The data gap surfaced
`TELEMETRY_GAP` / `LOW_DATA_COVERAGE` / `LIMITED_DATA` / `LIVE_DATA_SUFFICIENCY`
findings, i.e. missing data is reported rather than masked as healthy.

---

## 10. Limitations, threats to validity & recommendations

**Threats to validity**

1. **Synthetic only.** Telemetry is generated by the in-repo simulator. These are
   *simulated* results and do **not** establish real-world accuracy.
2. **Reference is the injected scenario**, not an independent sensor or
   engineering ground truth; there is no per-sample fault label beyond it.
3. **No independent health scale** → RQ2 is ordinal only; **no expert diagnoses**
   → RQ5 correctness is not evaluable.
4. **Deterministic rules, not a learned classifier**; "accuracy" means agreement
   with injected conditions, not statistical generalization.
5. **Single-host latency** with a monotonic clock; no external network/physical
   transport is measured. `publish → alert` (n=9) supports only a median.
6. **Scenario coverage** is four families; `RPM_UNUSUAL` and `FUEL_LEVEL_LOW`
   have no injected positive control and are unvalidated.
7. **RQ3 recovery** uses a second session as a stand-in for self-resolution.
8. **Host environment:** Python 3.14, local PostgreSQL without pgvector, RAG may
   degrade with `rag_reason="retrieval-error"`.

**Recommendations**

1. **Address cold-start false positives.** The rapid-rise rules fire on every
   ordinary warm-up on the live inclusive path (and in the `full` view). Gate
   rapid-rise findings behind an established operating temperature / a
   warm-up-suppressed baseline, or delay alert materialisation until the session
   is past the warm-up ramp. This is the highest-value correctness change.
2. **Do not cite RQ1/RQ2 numbers as accuracy** without the `steady`-view and
   synthetic caveats; always pair the 1.000 with the 0.250 `full`-view result.
3. **Collect more alert samples** (more fault episodes) before publishing p95/p99
   for `publish → alert`; n=9 justifies only the median.
4. **Author a MANUALLY_LABELLED reference set** for diagnosis if RQ5 correctness
   is ever required.
5. **Add injected positive controls** for `RPM_UNUSUAL` / `FUEL_LEVEL_LOW` to
   widen RQ1/RQ6 coverage.

---

## Appendix A — Reproduce

From `backend/` (requires a private Mosquitto install and a disposable
`digital_twin_eval_test` PostgreSQL database on loopback):

```powershell
# RQ3 alert lifecycle + RQ4 wall-clock latency + RQ6 robustness
python -m evaluation.pipeline all

# RQ1/RQ2 accuracy over the frozen scenario dataset
python -m evaluation all --dataset synthetic-scenarios-v2 --scenarios normal high_temperature low_battery high_engine_load --seeds 1 2 3 4 5
```

Each result directory holds `metrics.json` (single source of truth), `REPORT.md`
(rendered from those bytes), `README.md`, `provenance.json`, `PLAN_HASHES.json`
(frozen content hashes) and, for the pipeline set, `figures/*.svg`.

## Appendix B — Verification

| Check | Command (from `backend/`) | Result |
| --- | --- | --- |
| Hermetic evaluation tests | `python -m pytest tests/evaluation -q` | 39 passed |
| Lint | `python -m ruff check app tests evaluation tests/evaluation` | clean |
| MQTT integration | `python scripts/run_mqtt_integration.py -q` | 7 passed |
| Full backend suite | `python -m pytest -p no:cacheprovider --override-ini addopts= -m "not mqtt_e2e and not mqtt_integration"` | **776 passed, 10 skipped, 11 deselected** (exit 0, 602.03 s) |

## Appendix B.1 — Per-RQ evaluability verdicts (verbatim)

| RQ | Verdict |
| --- | --- |
| RQ1 fault detection | SIMULATED, measurable |
| RQ2 health assessment | SIMULATED, ordinal only (no absolute reference) |
| RQ3 alert lifecycle | SIMULATED episodes / MEASURED alerts |
| RQ4 latency | MEASURED (software pipeline, single host) |
| RQ5 AI diagnosis | **NOT EVALUABLE** (correctness); grounding only |
| RQ6 robustness | SIMULATED + MEASURED |
