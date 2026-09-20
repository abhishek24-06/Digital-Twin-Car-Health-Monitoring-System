.PHONY: install dev test lint format migrate migration docker-up docker-down shell

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