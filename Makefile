.PHONY: lint format typecheck test test\:unit test\:integration test\:coverage test\:ui build pack\:check security\:audit health check clean

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy .

test:
	uv run pytest tests/ -v

test\:unit:
	uv run pytest tests/ -v -m "not integration and not ui"

test\:integration:
	uv run pytest tests/ -v -m "integration"

test\:coverage:
	uv run pytest tests/ -v --cov=autoweave --cov-report=term-missing --cov-fail-under=75

test\:ui:
	uv run pytest tests/ -v -m "ui"

build: clean
	uv run --with build python -m build

pack\:check: build
	bash scripts/smoke_test.sh

security\:audit:
	uv run --with pip-audit pip-audit

health:
	uv run python scripts/health_report.py

check: lint test\:coverage

clean:
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ .mypy_cache/ .coverage reports/
