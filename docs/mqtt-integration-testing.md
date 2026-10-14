# MQTT integration testing (Phase C)

The MQTT ingestion path (broker → subscriber → PostgreSQL) is exercised against
a **real isolated Mosquitto broker** and a **dedicated disposable database**.
It is deliberately *not* part of the ordinary unit run: it needs a local
Mosquitto install and a disposable Postgres database.

## Run it

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.run_mqtt_integration
# or
make mqtt-integration
```

The wrapper defaults `DT_MQTT_TEST_DATABASE_URL` to
`postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_mqtt_test` and
runs `pytest -m mqtt_integration tests/mqtt`. Any extra arguments are forwarded:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_mqtt_integration -v
```

## Isolation contract (fail-closed)

The suite reads `DT_MQTT_TEST_DATABASE_URL`:

- **unset** → every test *skips*, so `pytest` on a laptop without a broker still
  behaves. The marker is excluded from `addopts`, so the ordinary `pytest` run
  never even selects these tests.
- **set** → it must be loopback (`127.0.0.1` / `localhost` / `::1`) and the
  database must be named exactly `digital_twin_mqtt_test`, and the host must not
  contain `supabase`, `pooler`, `amazonaws`, `render.com` or `neon.tech`.
  Anything else **raises** rather than silently running against real data.

The broker is a private `mosquitto` process bound to a free loopback port with
`persistence false`; it never reuses a developer's broker or its state. The
disposable database is created on demand and dropped/cleaned up afterwards, even
when a test fails.

## Requirements

- `mosquitto.exe` and `mosquitto_pub.exe` (Windows candidates under
  `C:\Program Files\mosquitto\`, or on `PATH`).
- A reachable local PostgreSQL.
- No pgvector extension (non-`rag_` tables only).

## Scenarios covered

| Test | Proves |
| --- | --- |
| publish + duplicate delivery | real messages persist; a repeated `event_id` does not create a second row |
| malformed / unknown / unrelated | bad JSON, wrong schema, unknown vehicle and unrelated topics are ignored without breaking the stream |
| out-of-order / delayed | an earlier timestamp delivered later still persists with its own timestamp order intact |
| broker restart | a hard broker stop makes the subscriber retry, then resume automatically |
| transient DB failure | a session factory that raises is retried until it succeeds |
| retry exhaustion | an always-failing DB is abandoned without crashing the subscriber |
| simulator restart | a real simulator subprocess publishes through the broker and a restart mints a distinct `run_id`, both remaining distinguishable in the database |

## Related

- Legacy broker-only suite: `make mqtt-test` (`-m mqtt_e2e`), which skips when
  no broker listens on `localhost:1883`.
- Roadmap/tracking: `docs/IMPLEMENTATION_ROADMAP.md`.
