# AutoWeave: Multi-Agent Orchestration Library

**AutoWeave** is the robust execution engine for multi-agent software engineering teams. It orchestrates specialized AI agents as a coherent team, managing workflow compilation, task graphs, queue-backed durable execution, and human-in-the-loop approvals.

## Core Features

- **Workflow Orchestration**: Define, compile, and execute Directed Acyclic Graphs (DAGs) of agentic tasks.
- **Durable State**: Resume paused runs, track individual attempts, and safely persist context to PostgreSQL.
- **Human-in-the-Loop**: Built-in primitives to pause execution and request approvals or clarifications from a human.
- **Queue Dispatch**: Offload long-running autonomous tasks to Celery workers backed by Redis.
- **Local Monitoring**: Inspect active and historic runs via a beautiful, lightweight local developer dashboard.

## Installation

Install AutoWeave directly from PyPI using pip or uv:

```bash
pip install autoweave
```

## Quick Start (CLI)

AutoWeave provides a comprehensive CLI for local orchestration.

1. **Initialize a new project** in a fresh directory:
```bash
autoweave new-project
```

2. **Bootstrap the local environment** and configuration files:
```bash
autoweave bootstrap
```

3. **Start the control plane UI** and background Celery worker:
```bash
autoweave start
```

4. **Execute a workflow** from the terminal:
```bash
autoweave run-workflow --root . --request "Create a Python script that calculates Fibonacci numbers"
```

## Programmatic Usage

AutoWeave exposes a clean Python API for integrating orchestration into your own applications.

### 1. Launching a Workflow
```python
from autoweave.orchestration.runtime import build_local_runtime

# Initialize the runtime for your project directory
runtime = build_local_runtime(root_path="./my-weave-project")

# Dispatch a new workflow to the agents
workflow_run = runtime.launch_workflow(
    request="Review the backend contract and propose next steps"
)
print(f"Successfully started workflow run: {workflow_run.id}")
```

### 2. Inspecting the State
```python
from autoweave.monitoring.service import MonitoringService

service = MonitoringService(db_path="./my-weave-project/autoweave.db")

# Fetch a snapshot of all active runs
state_snapshot = service.snapshot(limit=5)
print(state_snapshot)
```

## Dashboard & Monitoring

AutoWeave includes a built-in monitoring dashboard to trace agent executions, view generated artifacts, and resolve human-in-the-loop approvals.

To start it independently:
```bash
autoweave ui --root ./my-weave-project
```
Then navigate to `http://localhost:8766` in your browser.

## Support & Architecture

For comprehensive architecture specs, deployment instructions, and advanced configuration options, visit our [GitHub Repository Documentation](https://github.com/hypnoastic/Autoweave-Library).
