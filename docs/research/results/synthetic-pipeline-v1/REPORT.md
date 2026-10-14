# Digital Twin pipeline evaluation — RQ3/RQ4/RQ6 (EXECUTED)

- Dataset id: `synthetic-pipeline-v1`
- Generated: 2026-10-13T15:57:07.077306+00:00
- Provenance: SIMULATED (episodes) + MEASURED (pipeline behavior)
- Code revision: `66674bdccc1b8c6d56cd813cc2bd1d0a2e895f31`

## RQ3 — Alert lifecycle (live current-session path)

- Episodes: 12 (9 fault, 3 control), exposure 0.6000 vehicle-hours.
- Episode recall: 100.0% (9/9); episode precision: 75.0%.
- Expected-rule recall: 100.0% (12/12 episode-rule pairs).
- Alerts: 36 total, 12 matching, 24 false positive; alert precision 33.3%.
- False alarms: 40.000 per vehicle-hour.
- Duplicate alert rows: 0; recurrence-folded updates: 5752.
- Alerts provisional at creation: 30; definitive: 6.
- Time to first detection: n=9 min=1.000 p50=22.000 p95=n/a (not justified: n<20) p99=n/a (not justified: n<100) max=46.000 mean=23.222 [s]
- Unresolved within-episode alerts: 36 (a single fault episode cannot self-resolve).

### Per-episode outcome

| episode | scenario | reference | expected rules | alerts | matching | false positive | detected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| normal-seed1 | normal | none | (none) | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | (none) | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | no |
| normal-seed2 | normal | none | (none) | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | (none) | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | no |
| normal-seed3 | normal | none | (none) | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | (none) | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | no |
| high_temperature-seed1 | high_temperature | thermal | COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE, COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |
| high_temperature-seed2 | high_temperature | thermal | COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE, COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |
| high_temperature-seed3 | high_temperature | thermal | COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE, COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |
| low_battery-seed1 | low_battery | electrical | BATTERY_VOLTAGE_LOW | BATTERY_VOLTAGE_LOW, RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | BATTERY_VOLTAGE_LOW | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |
| low_battery-seed2 | low_battery | electrical | BATTERY_VOLTAGE_LOW | BATTERY_VOLTAGE_LOW, RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | BATTERY_VOLTAGE_LOW | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |
| low_battery-seed3 | low_battery | electrical | BATTERY_VOLTAGE_LOW | BATTERY_VOLTAGE_LOW, RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | BATTERY_VOLTAGE_LOW | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |
| high_engine_load-seed1 | high_engine_load | engine_load | ENGINE_LOAD_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE, ENGINE_LOAD_HIGH | ENGINE_LOAD_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |
| high_engine_load-seed2 | high_engine_load | engine_load | ENGINE_LOAD_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE, ENGINE_LOAD_HIGH | ENGINE_LOAD_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |
| high_engine_load-seed3 | high_engine_load | engine_load | ENGINE_LOAD_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE, ENGINE_LOAD_HIGH | ENGINE_LOAD_HIGH | RAPID_COOLANT_RISE, RAPID_OIL_TEMP_RISE | yes |

### Snapshot scope fed to the alert path

Every snapshot passed to `AlertService.sync_from_snapshot` must be a `current_session` evaluation (historical windowed analyses never create alerts).

| analysis_scope | snapshots |
| --- | --- |
| current_session | 2160 |

### Recovery (time to resolution)

A condition-free `normal` session runs on the same vehicle after each fault episode; a definitive pass that no longer observes the rule auto-resolves it.

- Cases: 3; resolved fault-rule alerts: 4.
- Time to resolution: n=4 min=30.000 p50=30.000 p95=n/a (not justified: n<20) p99=n/a (not justified: n<100) max=30.000 mean=30.000 [s]

| scenario | fault rules | resolved fault rules | TTR (s) |
| --- | --- | --- | --- |
| high_temperature | COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | COOLANT_TEMP_HIGH, OIL_TEMP_HIGH | 30.000 |
| low_battery | BATTERY_VOLTAGE_LOW | BATTERY_VOLTAGE_LOW | 30.000 |
| high_engine_load | ENGINE_LOAD_HIGH | ENGINE_LOAD_HIGH | 30.000 |

## RQ4 — Pipeline latency (wall clock, single host, monotonic)

- Wall-clock samples: 180; new alerts observed: 9; monitor failures: 0.

| stage | series |
| --- | --- |
| publish -> persisted telemetry row | n=180 min=2.482 p50=3.886 p95=6.763 p99=7.765 max=8.267 mean=4.364 [ms] |
| engine self-reported analyse duration | n=180 min=0.349 p50=1.201 p95=2.016 p99=2.653 max=3.137 mean=1.245 [ms] |
| monitor pass (analyse + alert sync) | n=180 min=7.403 p50=16.063 p95=22.928 p99=26.787 max=32.900 mean=16.491 [ms] |
| publish -> alert persisted | n=9 min=17.906 p50=21.837 p95=n/a (not justified: n<20) p99=n/a (not justified: n<100) max=54.309 mean=29.925 [ms] |

`publish → detection` and `publish -> alert` are the same instant here: a finding is materialised into a persisted alert synchronously in the same monitor pass, so the two are reported as one number rather than two.

- Publish-to-alert percentiles are not justified at this sample count; only the median should be used. Increase seed count/session length to justify p95/p99.

## RQ6 — Robustness under injected delivery/DB/broker faults

- Cases: 10; passed: 10/10.

| case | persisted | expected | passed | description | detail |
| --- | --- | --- | --- | --- | --- |
| clean_baseline | 5 | 5…5 | yes | 5 distinct valid samples delivered once each | baseline: no duplicate loss, no drops |
| duplicate_delivery | 1 | 1…1 | yes | the same (vehicle, event_id) delivered 5 times | idempotent on (vehicle_id, source_event_id) |
| repeated_event_ids | 2 | 2…2 | yes | ids [a,b,a,b] replayed across separate flushes | cross-batch dedup holds |
| out_of_order | 4 | 4…4 | yes | arrival order [3, 1, 2, 0], timestamp order 0..3 | stored timestamps sorted == True |
| delayed_message | 2 | 2…2 | yes | one sample stamped 42 min in the past | source timestamp preserved, not overwritten with arrival time |
| missing_interval | 4 | 4…4 | yes | samples at -30,-29,-28,-1 s (a 27 s gap) | data-quality findings: ['LIMITED_DATA', 'LIVE_DATA_SUFFICIENCY', 'LOW_DATA_COVERAGE', 'TELEMETRY_GAP'] |
| malformed_payloads | 1 | 1…1 | yes | 8 invalid envelopes (JSON/schema/tz/version/bounds) then 1 valid | invalid messages discarded; stream survived to persist the next valid one |
| unknown_vehicle | 1 | 1…1 | yes | a valid envelope for an unregistered vehicle, then a known one | unknown vehicle rows persisted: 0 |
| transient_db_failure | 4 | 4…4 | yes | first 2 session acquisitions raise DatabaseError (retry_attempts=3) | session-factory calls: 6; all samples eventually persisted |
| broker_restart | 7 | 4…1000 | yes | broker killed and relaunched mid-stream, then more samples | subscriber reconnected after 1.6s |

## Run provenance

- `python -m evaluation.pipeline all`

## Environment

- Platform: Windows-11-10.0.26200-SP0; Python 3.14.7
- Database: digital_twin_eval_test on 127.0.0.1 (disposable, loopback, fail-closed)
- Broker: 127.0.0.1:60637 (private mosquitto, persistence false)
- MQTT batch: max 1 message(s) / 5.0 s flush
- Analysis window: 15 min; interval 1.0 s

Clock semantics:
- `rq3_alerts`: replayed on the episode's synthetic clock: each persisted snapshot is re-analysed with generated_at=point.timestamp and fed to AlertService.sync_from_snapshot in timestamp order
- `rq3_recovery`: two sessions on one vehicle: fault session (synthetic clock T) then a condition-free normal session (clock T + 1 day) so the two never overlap
- `rq4_latency`: separate wall-clock streaming run (generated_at=None); ingest latency is publish_ts -> persisted created_at using a monotonic clock, so it is host-local and excludes any external network hop
- `rq6_robustness`: wall-clock injection against the live subscriber; injected faults and the resulting persisted row counts are measured, not simulated

## Limitations

- Synthetic telemetry produced by the in-repo simulator; this is a SIMULATED systems evaluation, not real-vehicle validation.
- The reference label is the scenario the harness injected, not an independent sensor or engineering ground truth.
- Alert quality is measured on the live current-session path only; historical windowed analyses are documented as never creating alerts, not scored.
- Publish-to-alert latency here means publish -> persisted alert row on one host with a monotonic clock; it excludes network hops outside this machine.
- Recovery (time-to-resolution) is modelled with a second, condition-free session on the same vehicle because a single fault episode cannot self-resolve.

