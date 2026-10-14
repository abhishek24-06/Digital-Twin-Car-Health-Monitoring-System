# Developer entrypoints for the Digital Twin backend.
#
# Cross-platform (Windows + POSIX). The venv interpreter is resolved per
# platform -- Windows venvs keep executables in .venv/Scripts/, POSIX in
# .venv/bin/ -- and recipes invoke tools through `python -m`, so no recipe
# depends on POSIX-only shell builtins. The interactive Bash `read -p` in
# `migration` is replaced by a Python prompt (scripts/make_migration.py).
.PHONY: install dev test lint format migrate migration db-verify db-check db-current db-heads db-history db-reset-local docker-up docker-down shell up down logs seed-demo-vehicle mqtt-subscriber simulator mqtt-test mqtt-broker mqtt-integration agent-llm-smoke

# Resolved lazily (recursive variable) so `make install` on a fresh checkout
# sees the venv it just created; falls back to a system `python`.
PY = $(firstword $(wildcard .venv/Scripts/python.exe) $(wildcard .venv/bin/python) $(wildcard .venv/Scripts/python) python)

.venv:
	python -m venv .venv

install: .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

dev:
	$(PY) -m uvicorn app.main:app --reload

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff check . --fix
	$(PY) -m ruff format .

migrate:
	$(PY) -m alembic upgrade head

# Verify the configured DATABASE_URL serves the pgvector schema (extension,
# HNSW index and operators). Used by CI after `alembic upgrade head`.
db-verify:
	$(PY) -m scripts.verify_pgvector

# Verify DATABASE_URL is reachable (independent probe; prints TLS status).
db-check:
	$(PY) -m scripts.check_db

# Inspect migration state/targets for the configured DATABASE_URL.
db-current:
	$(PY) -m alembic current
db-heads:
	$(PY) -m alembic heads
db-history:
	$(PY) -m alembic history --verbose

# Reset ONLY the schema of an explicitly local development database. The
# helper refuses (non-zero exit) when DATABASE_URL targets Supabase or any
# non-local host, so it can never repeat the accidental Supabase DROP SCHEMA.
db-reset-local:
	$(PY) -m scripts.reset_local_db --yes

# `make migration MESSAGE="..."` runs non-interactively; without MESSAGE the
# helper prompts for the message. The exported MESSAGE reaches the helper via
# the environment on every platform.
export MESSAGE
migration:
	$(PY) -m scripts.make_migration

docker-up:
	docker compose up --build

docker-down:
	docker compose down

shell:
	$(PY)

# ------------------------------------------------------------------ Phase 2

# Bring up the full Phase 2 stack (API + broker + subscriber + simulator).
up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

# Create the fixed demo vehicle the simulator publishes for (idempotent).
seed-demo-vehicle:
	$(PY) -m scripts.seed_demo_vehicle

# Run the MQTT subscriber standalone (uses .env broker + database settings).
mqtt-subscriber:
	$(PY) -m app.mqtt.subscriber

# Run the vehicle simulator standalone (requires SIMULATOR_VEHICLE_ID).
simulator:
	$(PY) -m simulator.main

# End-to-end suite against a real broker (start one with `make mqtt-broker`).
mqtt-test:
	$(PY) -m pytest -m mqtt_e2e

# Start a local (loopback-only, anonymous) Mosquitto broker for development.
mqtt-broker:
	mosquitto -c infrastructure/mosquitto/mosquitto.local.conf

# Phase C integration suite: real isolated Mosquitto + disposable database.
# Expects a local Mosquitto install; the disposable database URL defaults to a
# loopback `digital_twin_mqtt_test`. See docs/mqtt-integration-testing.md.
mqtt-integration:
	$(PY) -m scripts.run_mqtt_integration

# ------------------------------------------------------------------ Phase 4

# Gate-controlled live LLM smoke test (real provider key required in .env).
# The gate is injected via runpy so this target works on Windows too (the
# POSIX-only `VAR=value cmd` prefix is avoided).
agent-llm-smoke:
	$(PY) -c "import os,runpy; os.environ['RUN_LLM_SMOKE_TEST']='true'; runpy.run_module('scripts.smoke_agent_llm', run_name='__main__')"