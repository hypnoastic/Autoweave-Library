# AutoWeave: Multi-Agent Orchestration Library

**AutoWeave** is the execution engine for multi-agent software engineering teams. It orchestrates specialized AI agents as a coherent team, managing workflow compilation, task graphs, queue-backed durable execution, and human-in-the-loop approvals.

## What is AutoWeave?

AutoWeave owns the orchestration layer, explicitly decoupled from the single-agent execution layer (e.g., OpenHands). 

- **Workflow Orchestration**: Define, compile, and execute DAGs of agentic tasks with dependency-aware dynamic scheduling.
- **Durable State**: Resume paused runs, track attempts, and persist context safely across PostgreSQL.
- **Human-in-the-Loop**: Native primitives for pausing execution to request approvals or clarifications.
- **Queue Dispatch**: Offload long-running tasks to Celery workers backed by Redis.
- **Local Monitoring**: Inspect runs via a lightweight local dashboard and playground.

## Installation

You can install AutoWeave via pip:

```bash
pip install autoweave
```

## Quick Start

Initialize a new AutoWeave project in a fresh directory:

```bash
autoweave new-project
```

Next, bootstrap the local environment and configurations:

```bash
autoweave bootstrap
```

Start the control plane UI and Celery worker:

```bash
autoweave start
```

## CLI Reference

The `autoweave` CLI provides complete control over your local environment. Here are the core commands:
- `status`: Show a minimal repository status summary.
- `validate`: Validate docs, configs, and sample agent fixtures.
- `create-agent`: Create a new agent bundle with soul, playbook, config, and skills.
- `run-workflow`: Run the current workflow from a user request.

Run `autoweave --help` for the full list of options.

## Support
For comprehensive architecture specs and deployment instructions, visit our GitHub repository documentation.
