.PHONY: install test test-unit test-integration test-property lint typecheck fmt run-api run-worker docker-up docker-down

install:
	pip install -e ".[dev]"

test:
	pytest

test-unit:
	pytest tests/unit -v

test-integration:
	pytest tests/integration -v

test-property:
	pytest tests/property -v

lint:
	ruff check src tests

fmt:
	ruff format src tests

typecheck:
	mypy src

run-api:
	uvicorn legal_engine.api.main:app --reload --port 8000

run-worker:
	celery -A legal_engine.workers.celery_app worker --loglevel=info

docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down
