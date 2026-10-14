# Exploratory Data Analysis — Digital Twin evaluation

**Provenance: SIMULATED telemetry + MEASURED pipeline behaviour.** Post-hoc and exploratory;
**not** the frozen pre-registration, and not a scored result.

## Artifacts

| File | Contents |
| --- | --- |
| `eda_metrics.json` | All computed statistics; the single source of truth. |
| `EDA.md` | Human-readable report rendered from `eda_metrics.json`. |
| `figures/*.png` | matplotlib/seaborn figures. |
| `provenance.json` | Input hashes, library versions, commands, limitations. |

## Reproduce

From `backend/`:

```
python -m evaluation.eda --force
```

## Inputs

- Scenarios dataset: `synthetic-scenarios-v2` (revision `66674bdccc1b8c6d56cd813cc2bd1d0a2e895f31`)
- Pipeline dataset: `synthetic-pipeline-v1`
- Episodes: 20; points: 3600

Figures: fig01_feature_separability.png, fig02_scenario_profile.png, fig03_correlation.png, fig04_warmup.png, fig05_feature_distributions.png, fig06_health_scores.png, fig07_rq1_confusion.png, fig08_findings.png, fig09_latency.png, fig10_alert_outcomes.png, fig11_robustness.png

