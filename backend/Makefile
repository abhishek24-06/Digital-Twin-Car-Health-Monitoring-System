.PHONY: install dev test lint format migrate migration docker-up docker-down shell up down logs seed-demo-vehicle mqtt-subscriber simulator mqtt-test mqtt-broker

install:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

dev:
	.venv/bin/uvicorn app.main:app --reload

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

format:
	.venv/bin/ruff check . --fix
	.venv/bin/ruff format .

migrate:
	.venv/bin/alembic upgrade head

migration:
	@read -p "Message: " msg; .venv/bin/alembic revision --autogenerate -m "$$msg"

docker-up:
	docker compose up --build

docker-down:
	docker compose down

shell:
	.venv/bin/python

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
	.venv/bin/python -m scripts.seed_demo_vehicle

# Run the MQTT subscriber standalone (uses .env broker + database settings).
mqtt-subscriber:
	.venv/bin/python -m app.mqtt.subscriber

# Run the vehicle simulator standalone (requires SIMULATOR_VEHICLE_ID).
simulator:
	.venv/bin/python -m simulator.main

# End-to-end suite against a real broker (start one with `make mqtt-broker`).
mqtt-test:
	.venv/bin/pytest -m mqtt_e2e

# Start a local (loopback-only, anonymous) Mosquitto broker for development.
mqtt-broker:
	mosquitto -c infrastructure/mosquitto/mosquitto.local.conf