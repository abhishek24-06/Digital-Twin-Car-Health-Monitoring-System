# Accuracy Evaluation — `synthetic-scenarios-v2`

**Provenance tag:** `SIMULATED`
**Generated:** 2026-10-13T15:05:10.440716+00:00

This report is **simulated** (synthetic telemetry). It is not a
real-world accuracy claim. See the limitations at the end.

## Commands executed

- `python -m evaluation all --dataset synthetic-scenarios-v2 --scenarios normal high_temperature low_battery high_engine_load --seeds 1 2 3 4 5`

## Dataset provenance

- dataset_id: `synthetic-scenarios-v2`
- generator: `backend/simulator/telemetry_generator.SimulationEngine (unmodified)`
- reference_source: harness-injected-scenario
- label_method: injected-physical-condition
- label_version: 1.0
- code_revision: `66674bdccc1b8c6d56cd813cc2bd1d0a2e895f31`
- episodes: 20
- provenance: SIMULATED

## RQ1 fault detection — `steady` (PRIMARY fault-detection view)

Episodes: 20

### Per-episode expected-rule detection

| scenario | reference family | episodes | detected expected | false-positive episodes |
|---|---|---|---|---|
| normal | none | 5 | 0 | 0 |
| high_temperature | thermal | 5 | 5 | 0 |
| low_battery | electrical | 5 | 5 | 0 |
| high_engine_load | engine_load | 5 | 5 | 0 |

### Alert-worthy rule frequency

| scenario | alert-worthy rule | episodes |
|---|---|---|
| normal | _(none)_ | 0 |
| high_temperature | COOLANT_TEMP_HIGH | 5 |
| high_temperature | OIL_TEMP_HIGH | 5 |
| low_battery | BATTERY_VOLTAGE_LOW | 5 |
| high_engine_load | ENGINE_LOAD_HIGH | 5 |

### Family classification

- accuracy: 1.000
- macro-F1: 1.000
- weighted-F1: 1.000

| true \ pred | thermal | electrical | engine_load | engine_speed | fuel | none |
|---|---|---|---|---|---|---|
| thermal | 5 | 0 | 0 | 0 | 0 | 0 |
| electrical | 0 | 5 | 0 | 0 | 0 | 0 |
| engine_load | 0 | 0 | 5 | 0 | 0 | 0 |
| engine_speed | 0 | 0 | 0 | 0 | 0 | 0 |
| fuel | 0 | 0 | 0 | 0 | 0 | 0 |
| none | 0 | 0 | 0 | 0 | 0 | 5 |

### Per-label precision / recall / F1

| label | support | predicted | precision | recall | F1 |
|---|---|---|---|---|---|
| thermal | 5 | 5 | 1.000 | 1.000 | 1.000 |
| electrical | 5 | 5 | 1.000 | 1.000 | 1.000 |
| engine_load | 5 | 5 | 1.000 | 1.000 | 1.000 |
| none | 5 | 5 | 1.000 | 1.000 | 1.000 |

### RQ2 — ordinal health discrimination (no regression metrics)

- No independent continuous health reference exists; regression metrics (MAE/RMSE/R2) are intentionally NOT computed. AUC is ordinal discrimination of the injected condition, not accuracy. The status confusion is descriptive and partly circular (status buckets and rules share thresholds).
- AUC (anomaly vs. normal): 1.000 (n_anomaly=15, n_normal=5)
- AUC (thermal vs. non-thermal): 1.000

| reference family | n | min | median | max | mean |
|---|---|---|---|---|---|
| thermal | 5 | 60.0 | 60.0 | 60.0 | 60.0 |
| electrical | 5 | 90.0 | 90.0 | 90.0 | 90.0 |
| engine_load | 5 | 90.0 | 90.0 | 90.0 | 90.0 |
| none | 5 | 100.0 | 100.0 | 100.0 | 100.0 |

Status confusion (partly circular — status buckets share thresholds):

- none: healthy: 5
- thermal: attention: 5
- electrical: healthy: 5
- engine_load: healthy: 5

### RQ4 compute latency (software, MEASURED)

- MEASURED software compute latency of HealthAnalysisEngine.analyze per episode (analysis_duration_ms). Publish-to-alert pipeline latency requires the isolated MQTT+DB harness and is NOT measured here.
- analysis_duration_ms: n=20 min=1.368 p50=1.395 p95=1.47 p99=n/a (not justified: n<100) max=1.805 mean=1.425

## RQ1 fault detection — `full` (warm-up-sensitivity / false-positive view)

Episodes: 20

### Per-episode expected-rule detection

| scenario | reference family | episodes | detected expected | false-positive episodes |
|---|---|---|---|---|
| normal | none | 5 | 0 | 5 |
| high_temperature | thermal | 5 | 5 | 0 |
| low_battery | electrical | 5 | 5 | 0 |
| high_engine_load | engine_load | 5 | 5 | 0 |

### Alert-worthy rule frequency

| scenario | alert-worthy rule | episodes |
|---|---|---|
| normal | RAPID_COOLANT_RISE | 5 |
| normal | RAPID_OIL_TEMP_RISE | 5 |
| high_temperature | COOLANT_TEMP_HIGH | 5 |
| high_temperature | OIL_TEMP_HIGH | 5 |
| high_temperature | RAPID_COOLANT_RISE | 5 |
| high_temperature | RAPID_OIL_TEMP_RISE | 5 |
| low_battery | BATTERY_VOLTAGE_LOW | 5 |
| low_battery | RAPID_COOLANT_RISE | 5 |
| low_battery | RAPID_OIL_TEMP_RISE | 5 |
| high_engine_load | ENGINE_LOAD_HIGH | 5 |
| high_engine_load | RAPID_COOLANT_RISE | 5 |
| high_engine_load | RAPID_OIL_TEMP_RISE | 5 |

### Family classification

- accuracy: 0.250
- macro-F1: 0.100
- weighted-F1: 0.100

| true \ pred | thermal | electrical | engine_load | engine_speed | fuel | none |
|---|---|---|---|---|---|---|
| thermal | 5 | 0 | 0 | 0 | 0 | 0 |
| electrical | 5 | 0 | 0 | 0 | 0 | 0 |
| engine_load | 5 | 0 | 0 | 0 | 0 | 0 |
| engine_speed | 0 | 0 | 0 | 0 | 0 | 0 |
| fuel | 0 | 0 | 0 | 0 | 0 | 0 |
| none | 5 | 0 | 0 | 0 | 0 | 0 |

### Per-label precision / recall / F1

| label | support | predicted | precision | recall | F1 |
|---|---|---|---|---|---|
| thermal | 5 | 20 | 0.250 | 1.000 | 0.400 |
| electrical | 5 | 0 | 0.000 | 0.000 | 0.000 |
| engine_load | 5 | 0 | 0.000 | 0.000 | 0.000 |
| none | 5 | 0 | 0.000 | 0.000 | 0.000 |

### RQ2 — ordinal health discrimination (no regression metrics)

- No independent continuous health reference exists; regression metrics (MAE/RMSE/R2) are intentionally NOT computed. AUC is ordinal discrimination of the injected condition, not accuracy. The status confusion is descriptive and partly circular (status buckets and rules share thresholds).
- AUC (anomaly vs. normal): 1.000 (n_anomaly=15, n_normal=5)
- AUC (thermal vs. non-thermal): 1.000

| reference family | n | min | median | max | mean |
|---|---|---|---|---|---|
| thermal | 5 | 60.0 | 60.0 | 60.0 | 60.0 |
| electrical | 5 | 70.0 | 70.0 | 70.0 | 70.0 |
| engine_load | 5 | 70.0 | 70.0 | 70.0 | 70.0 |
| none | 5 | 80.0 | 80.0 | 80.0 | 80.0 |

Status confusion (partly circular — status buckets share thresholds):

- none: healthy: 5
- thermal: attention: 5
- electrical: attention: 5
- engine_load: attention: 5

### RQ4 compute latency (software, MEASURED)

- MEASURED software compute latency of HealthAnalysisEngine.analyze per episode (analysis_duration_ms). Publish-to-alert pipeline latency requires the isolated MQTT+DB harness and is NOT measured here.
- analysis_duration_ms: n=20 min=3.533 p50=3.697 p95=4.1 p99=n/a (not justified: n<100) max=4.316 mean=3.775

## RQ2 / RQ5 status

- **RQ2 (health vs. independent reference):** SIMULATED, ordinal only. No independent continuous health reference exists, so no MAE/RMSE/R2 is reported and AUC must not be read as accuracy.
- **RQ5 (AI diagnosis correctness):** NOT EVALUABLE. No expert-labelled reference diagnoses exist; only the grounding contract can be measured.

## Limitations

- SYNTHETIC ONLY: telemetry comes from the in-repo simulator; this is not real-world validation.
- No independent continuous health reference exists; RQ2 is ordinal discrimination only (no MAE/RMSE/R2).
- No expert-labelled reference diagnoses exist; RQ5 correctness is NOT EVALUABLE (only the grounding contract can be measured).
- The analyzer is deterministic rule logic, not a learned classifier; 'accuracy' means agreement with injected conditions.
- The 'full' view includes cold-start warm-up and is expected to raise false-positive rapid-rise findings.
- Only four simulator scenarios exist; rules without an injected positive control cannot be validated here.
