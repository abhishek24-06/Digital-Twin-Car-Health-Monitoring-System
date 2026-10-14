# Evaluation results — `synthetic-scenarios-v1`

**Provenance: `SIMULATED`.** These results are generated from the in-repo
simulator. They are **not** real-world validation and must not be reported as
such. See `../../accuracy_evaluation_plan.md` for the frozen pre-registration.

## Artifacts

| File | Contents |
| --- | --- |
| `provenance.json` | Dataset manifest: generator, seeds, label method, code revision, limitations. |
| `dataset.json` | Full generated episodes (per-sample telemetry) with per-episode provenance. |
| `metrics.json` | Per-view RQ1/RQ2/RQ4 aggregates + per-episode result records. |
| `REPORT.md` | Human-readable report rendered from `metrics.json`. |

## Reproduce

From `backend/`:

```
python -m evaluation all --seeds 1 2 3 4 5
```

Generation is deterministic (seeded `SimulationEngine`, fixed synthetic epoch,
pinned generation fields), so re-running on the same code revision reproduces the
same dataset and metrics.

## What was executed

- Command: `python -m evaluation all --seeds 1 2 3 4 5`
- Engine: the **shipped** `app.intelligence.engine.HealthAnalysisEngine`
  (imported, not copied) and the in-repo `simulator.telemetry_generator.SimulationEngine`.
- The health algorithm, thresholds, scoring, alert logic and prompts were **not
  modified**.

## Headline results (summary only — see `REPORT.md` for the full tables)

Two pre-registered analysis views (plan §4.1.1):

- **`steady`** (last 60 s, primary fault-detection view): 20 episodes
  (4 scenarios × 5 seeds), per-family accuracy **1.000**, macro/weighted F1
  **1.000**; every injected condition detected at its expected severity; the
  `normal` control produced **no** alert-worthy finding.
- **`full`** (whole 180 s window, warm-up-sensitivity view): per-family accuracy
  **0.250**. The `normal` control raised `RAPID_COOLANT_RISE` and
  `RAPID_OIL_TEMP_RISE` in **5/5** episodes — i.e. ordinary cold-start warm-up is
  flagged as an alert-worthy (warning) finding. This also misclassifies every
  `low_battery` / `high_engine_load` episode as `thermal` in this view.

RQ2 (health assessment) is **ordinal only**: AUC(anomaly vs normal) = 1.000,
AUC(thermal vs non-thermal) = 1.000; no regression metrics (no independent
reference exists). Observed status behaviour (descriptive, partly circular):
warning-only faults scored 90 → `health_status = healthy`; the critical+warning
thermal fault scored 60 → `attention`.

RQ4 compute latency (MEASURED, software): `analysis_duration_ms` p50 ≈ 1.4 ms,
p95 ≈ 1.6 ms across 20 episodes. Publish-to-alert pipeline latency is **not**
measured here.

## Not yet executed (honest status)

- **RQ3 alert false-positive / miss / duplicate / time-to-detection** — requires
  driving the real `AlertService.sync_from_snapshot` against an isolated
  disposable database; not run in this pass.
- **RQ4 end-to-end pipeline latency** — requires the isolated MQTT + DB harness;
  not run in this pass.
- **RQ5 AI-diagnosis correctness** — **NOT EVALUABLE**: no expert-labelled
  reference diagnoses exist. Only the grounding-contract metrics (implemented in
  `backend/evaluation/metrics/diagnosis.py`) are available, and they are not
  diagnostic accuracy.
- **RQ6 robustness** (duplicate / malformed / out-of-order / delayed data) —
  infrastructure specified, not executed.

## Reproduction / integrity commands

```
# from backend/
python -m pytest tests/evaluation -q      # 22 metric/scenario regression tests
python -m ruff check evaluation tests/evaluation
python -m evaluation all --seeds 1 2 3 4 5
```
