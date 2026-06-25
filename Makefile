.PHONY: lint typecheck test test\:unit test\:integration test\:coverage test\:ui build pack\:check security\:audit

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy .

test:
	uv run pytest tests/ -v

test\:unit:
	uv run pytest tests/ -v -m "not integration and not ui"

test\:integration:
	uv run pytest tests/test_orchestration.py tests/test_local_runtime.py -v

test\:coverage:
	uv run pytest tests/ -v --cov=autoweave --cov-report=term-missing --cov-fail-under=80

test\:ui:
	uv run pytest tests/test_ui.py -v

build:
	uv pip install build
	uv run python -m build

pack\:check: build
	bash scripts/smoke_test.sh

security\:audit:
	uv pip install pip-audit
	uv run pip-audit
