# AutoWeave Library

AutoWeave is a terminal-first multi-agent orchestration library built around OpenHands remote workers and Vertex AI.

This library is the execution engine behind AutoWeave. It manages workflow compilation, task orchestration, queue-backed durable execution, and human-in-the-loop approvals.

[![CI](https://github.com/autoweave/autoweave-library/actions/workflows/ci.yml/badge.svg)](https://github.com/autoweave/autoweave-library/actions/workflows/ci.yml)
[![Security](https://github.com/autoweave/autoweave-library/actions/workflows/security.yml/badge.svg)](https://github.com/autoweave/autoweave-library/actions/workflows/security.yml)
[![Coverage](https://img.shields.io/badge/Coverage-80%25%2B-success.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](#)

## Features

- **Workflow Orchestration**: Define, compile, and execute DAGs of agentic tasks.
- **Durable State**: Resume paused runs, track attempts, and persist context safely.
- **Human-in-the-Loop**: Native primitives for pausing execution to request approvals or clarifications.
- **Queue Dispatch**: Offload long-running tasks to Celery workers.
- **Local Monitoring**: Inspect local runs natively via a lightweight local dashboard.

## Installation

AutoWeave Library is published as a Python package.

### Prerequisites
* Python >= 3.10

### Install via pip

```bash
pip install autoweave
```

### Install via uv (Recommended)

```bash
uv pip install autoweave
```

## Quick Start

### 1. Initialize a Project Root

AutoWeave requires a project directory to store local configurations.

```bash
autoweave new-project ./my-weave-project
autoweave bootstrap --root ./my-weave-project
```

### 2. Run a Simple Workflow

```bash
autoweave run-workflow \
    --root ./my-weave-project \
    --request "Write a script that prints Hello World"
```

### 3. Start the Monitoring UI

You can view the execution state, DAG, and manager chat locally:

```bash
autoweave ui --root ./my-weave-project
```
Navigate to `http://localhost:8765` to use the interactive playground and documentation.

## API Overview

You can also use AutoWeave programmatically:

```python
from autoweave.orchestration.runtime import build_local_runtime

# Initialize the runtime
runtime = build_local_runtime(root_path="./my-project")

# Launch a workflow programmaticly
workflow_run = runtime.launch_workflow(
    request="Review the backend contract and propose next steps"
)

print(f"Started run: {workflow_run.id}")
```

## Quality & Security

This library is designed with production-readiness in mind.

* **Automated CI**: Validates linting (Ruff), typechecking (Mypy), tests (Pytest), and builds `.whl` packages. A package smoke test is run to ensure publishable states.
* **Test Suite**: Covers core logic, integration flows, UI/docs behavior, and edge cases with a strict 80%+ overall coverage target.
* **Security Checks**: Automated workflows check dependencies via `pip-audit`, run CodeQL static analysis, and execute secret scanning.
* **Release Process**: Package release is designed for safe publishing to PyPI using Trusted Publishing (OIDC), preventing the need for long-lived repository secrets.
* **Architecture Constraints**: No backend/API surface, auth, or product databases are added because this project is purely an execution library.

## Testing

Run the test suite locally:
```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Contributing
1. Fork the repo.
2. Install dependencies via `uv pip install -e ".[dev]"`.
3. Make your changes.
4. Verify tests pass and run `autoweave ui` to check local UI.
5. Open a Pull Request.

## License
MIT
