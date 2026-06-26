# Development Guide

This document covers everything you need to develop, debug, and extend AutoWeave locally.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Environment Setup](#environment-setup)
- [Project Structure](#project-structure)
- [Configuration Reference](#configuration-reference)
- [Docker Setup](#docker-setup)
- [Makefile Reference](#makefile-reference)
- [Common Workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | ≥ 3.10 | Runtime |
| [uv](https://docs.astral.sh/uv/) | Latest | Package management |
| Docker | ≥ 24.0 | Container runtime |
| Docker Compose | ≥ 2.20 | Multi-service orchestration |
| Git | ≥ 2.40 | Version control |

---

## Environment Setup

### 1. Clone and Install

```bash
git clone https://github.com/hypnoastic/Autoweave.git
cd Autoweave

# Install with dev dependencies
uv pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### 2. Configure Environment

```bash
# Copy the template
cp .env.example .env.local

# Edit with your local values
# At minimum, configure:
#   - VERTEXAI_PROJECT (if using Vertex AI)
#   - REDIS_URL (default: redis://127.0.0.1:6379/0)
```

### 3. Service Account (Optional)

For Vertex AI integration:

```bash
# Place your service account key
mkdir -p config/secrets
cp /path/to/your/vertex_service_account.json config/secrets/
```

### 4. Verify Installation

```bash
# Check the CLI works
autoweave --help

# Run the test suite
make test

# Run all quality checks
make check
```

---

## Project Structure

```
autoweave/
├── autoweave/                 # Core library package
│   ├── __init__.py            # Public API surface
│   ├── models.py              # Pydantic domain models (Task, Attempt, Artifact, etc.)
│   ├── settings.py            # Environment configuration & path resolution
│   ├── protocols.py           # Protocol/interface definitions
│   ├── exceptions.py          # Custom exception hierarchy
│   ├── types.py               # Shared type aliases
│   ├── config_models.py       # Configuration schema models
│   ├── local_runtime.py       # Local development runtime (main entry point)
│   ├── celery_app.py          # Celery application factory
│   ├── celery_queue.py        # Queue-backed durable execution
│   ├── celery_tasks.py        # Celery task definitions
│   ├── project.py             # Project bootstrapping
│   ├── approvals/             # Approval service for human-in-the-loop
│   ├── artifacts/             # Artifact storage, filesystem, registry
│   ├── compiler/              # Workflow config compiler (YAML → runtime config)
│   ├── context/               # Context resolution (layered lookup)
│   ├── events/                # Domain event schemas & streaming
│   ├── graph/                 # Neo4j graph backend & projection
│   ├── memory/                # Memory layers (episodic, semantic, procedural)
│   ├── monitoring/            # Dashboard UI, contracts, web server
│   ├── observability/         # OpenTelemetry tracing, metrics, debug
│   ├── orchestration/         # Core orchestration: state machine, scheduler, service
│   ├── routing/               # Model routing policy engine
│   ├── storage/               # PostgreSQL repos, durable state, coordination
│   ├── templates/             # Project bootstrapping templates
│   ├── workers/               # OpenHands worker runtime management
│   └── workflows/             # Workflow specification parsing
├── apps/
│   └── cli/                   # Typer CLI (main.py, bootstrap.py, validation.py)
├── tests/                     # Full test suite
├── scripts/                   # Automation (smoke test, health report)
├── docs/                      # Architecture & design docs
└── config/secrets/            # Local secrets (git-ignored)
```

### Key Modules

| Module | Responsibility |
|---|---|
| `local_runtime` | Main runtime entry point — coordinates all services |
| `orchestration/state` | Task state machine with strict transition rules |
| `orchestration/scheduler` | Dependency-aware task scheduling |
| `storage/durable` | PostgreSQL-backed durable state persistence |
| `storage/coordination` | Redis-backed distributed coordination (leases, heartbeats) |
| `compiler/` | Compiles YAML workflow definitions → runtime task configs |
| `monitoring/service` | Real-time monitoring and dashboard data |
| `workers/runtime` | OpenHands remote worker lifecycle management |

---

## Configuration Reference

AutoWeave uses environment variables loaded from `.env.local`. See [`.env.example`](.env.example) for the complete reference.

### Core Services

| Variable | Required | Description |
|---|---|---|
| `REDIS_URL` | Yes | Redis connection (queue, coordination) |
| `POSTGRES_URL` | For durable mode | PostgreSQL connection (canonical state) |
| `NEO4J_URL` | For graph queries | Neo4j connection |

### Vertex AI

| Variable | Required | Description |
|---|---|---|
| `VERTEXAI_PROJECT` | For AI features | Google Cloud project |
| `VERTEXAI_LOCATION` | No | Region (default: `global`) |
| `VERTEXAI_SERVICE_ACCOUNT_FILE` | For AI features | Path to service account JSON |

### OpenHands

| Variable | Required | Description |
|---|---|---|
| `OPENHANDS_AGENT_SERVER_BASE_URL` | For workers | OpenHands server URL |
| `OPENHANDS_WORKER_TIMEOUT_SECONDS` | No | Worker timeout (default: 1800) |

---

## Docker Setup

### Full Stack

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f autoweave-runtime

# Check health
docker compose ps
```

### Services

| Service | Port | Purpose |
|---|---|---|
| `redis` | 6379 | Queue & coordination |
| `artifact-store` | — | Artifact storage volume |
| `autoweave-runtime` | — | AutoWeave runtime container |
| `openhands-agent-server` | 8000 | OpenHands worker server |

### Rebuild After Changes

```bash
docker compose build autoweave-runtime
docker compose up -d autoweave-runtime
```

---

## Makefile Reference

```bash
make lint              # Ruff check + format check
make format            # Auto-fix formatting
make typecheck         # Mypy type checking
make test              # Run all tests
make test:unit         # Unit tests only
make test:integration  # Integration tests only
make test:coverage     # Tests with coverage report (80% threshold)
make test:ui           # Playwright UI tests
make build             # Build wheel package
make pack:check        # Build + smoke test
make security:audit    # pip-audit dependency scan
make health            # Generate project health report
make check             # Run all checks (lint + typecheck + test:coverage)
make clean             # Remove build artifacts
```

---

## Common Workflows

### Adding a New Module

1. Create the module under `autoweave/<module_name>/`
2. Add `__init__.py` with public exports
3. Add the module to `autoweave/__init__.py` if it's part of the public API
4. Create tests in `tests/test_<module_name>.py`
5. Run `make check` to verify

### Adding a CLI Command

1. Edit `apps/cli/main.py`
2. Follow the existing Typer pattern
3. Add tests in `tests/test_cli.py`

### Modifying Domain Models

1. Edit `autoweave/models.py`
2. Update state transition rules if applicable
3. Update tests in `tests/test_runtime.py` or `tests/test_local_runtime.py`
4. Verify with `make test:coverage`

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'autoweave'`

Ensure you've installed in development mode:

```bash
uv pip install -e ".[dev]"
```

### Tests fail with Redis connection errors

Start Redis locally or via Docker:

```bash
# Via Docker
docker run -d -p 6379:6379 redis:7-alpine

# Or via docker-compose
docker compose up -d redis
```

### Mypy reports missing imports

This is expected for some optional dependencies. The `ignore_missing_imports = true` setting in `pyproject.toml` handles this. Only fix mypy errors for first-party code.

### Pre-commit hooks fail

Run the hooks manually to see detailed output:

```bash
pre-commit run --all-files
```

If hooks are outdated:

```bash
pre-commit autoupdate
```

### Docker build fails

Ensure Docker has sufficient resources and rebuild without cache:

```bash
docker compose build --no-cache autoweave-runtime
```

### Coverage below threshold

Run coverage with verbose output to identify gaps:

```bash
uv run pytest tests/ -v --cov=autoweave --cov-report=term-missing
```
