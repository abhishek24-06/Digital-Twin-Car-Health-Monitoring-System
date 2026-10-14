# Pipeline evaluation — `synthetic-pipeline-v1`

**Provenance: `SIMULATED` episodes + `MEASURED` pipeline behaviour.** The
telemetry is produced by the in-repo simulator; the pipeline behaviour it drives (MQTT ingestion, persistence, the live alert path, latency and fault tolerance) is measured on the real services. This is **not** real-vehicle validation.

## Artifacts

| File | Contents |
| --- | --- |
| `metrics.json` | Serialized measurements; the single source of truth. |
| `REPORT.md` | Human-readable report rendered from the bytes of `metrics.json`. |
| `provenance.json` | Run metadata, environment and per-section configuration. |
| `PLAN_HASHES.json` | sha256 of the frozen protocol and analyzer files. |
| `figures/*.svg` | Dependency-free figures rendered from `metrics.json`. |

## Reproduce

From `backend/` (requires a private Mosquitto broker and a dedicated disposable
PostgreSQL database named `digital_twin_eval_test` on loopback):

```
python -m evaluation.pipeline all
```

The **fail-closed** isolation guard refuses any non-loopback or differently named
database before a single row is touched. If the broker or database is unavailable
the run is recorded `NOT EXECUTED` with the blocker, never a fabricated result.

## Commands recorded in this result set

- `python -m evaluation.pipeline all`
