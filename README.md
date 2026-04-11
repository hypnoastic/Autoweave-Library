# AutoWeave Library

AutoWeave is the runtime and orchestration layer behind the AutoWeave product.

In this workspace, it sits under the web product as the execution engine:

- `Autoweave Web/` owns product UI, product APIs, chat/orbit/workflow surfaces, and product data.
- `Autoweave Library/` owns workflow execution, task orchestration, approvals, human clarification pauses, artifacts, routing, context services, observability, and the lightweight local monitoring UI.

The intended boundary is package-based, not source-coupled. The web backend installs this library as a real Python package and consumes it through that installed boundary.

## What This Repo Is For

This repo is for the reusable runtime, not the product shell.

Use it when you need:

- workflow orchestration with durable run/task state
- manager/worker style agent execution
- queue-backed execution with Celery
- human-in-the-loop clarification and approval pauses
- artifact emission and replay/manifest handling
- local runtime bootstrapping for an AutoWeave project
- a local monitoring UI for inspecting runs, tasks, attempts, requests, and artifacts

This repo is not the place for:

- the AutoWeave Web dashboard or orbit UX
- product chat persistence and product-level permissions
- web app routing/layout code
- product-side repository/member UI

## Current Capability Summary

Today this library provides:

- project bootstrap and migration helpers
- a local runtime builder
- workflow execution commands for example and real user requests
- queue-backed dispatch and a real Celery worker entrypoint
- local doctor/validate/status commands
- local cleanup helpers for generated runtime state
- a lightweight monitoring UI served from the monitoring module
- public helpers for bootstrapping and migrating AutoWeave projects from Python

## High-Level Runtime Model

AutoWeave treats the workflow runtime as the canonical execution layer.

At a high level:

1. A user request enters through a caller such as `autoweave run-workflow` or the web product.
2. The runtime compiles the request into a workflow run plus task graph.
3. Tasks are routed to agent roles and can run inline or through Celery-backed dispatch.
4. The runtime persists workflow runs, tasks, attempts, events, human requests, approvals, and artifacts.
5. If a workflow needs clarification or approval, execution pauses in the runtime until the request is answered.
6. Monitoring surfaces the current snapshot of runs, tasks, requests, attempts, and artifacts.

## How It Fits With AutoWeave Web

The most important architectural rule in this workspace is:

- `Autoweave Web` owns product UX, product auth, product navigation, inbox/dashboard/orbit surfaces, and repository/member workflows.
- `Autoweave Library` owns execution semantics, durable workflow state, queueing, artifacts, approval pauses, and monitoring.

That means when you are deciding where a change belongs:

- edit the library when you are changing how workflows compile, execute, pause, resume, persist, emit artifacts, or expose runtime status
- edit the web product when you are changing product APIs, GitHub auth/install flows, inbox/dashboard/orbit UX, or other product-facing views
- keep the boundary package-based: the web backend should install and call the library, not import arbitrary source files across repos

In practice, the web product should treat this repo as the control-plane runtime dependency that feeds product surfaces such as inbox summaries, orbit activity, workflow state, and monitoring drill-downs.

## Repo Layout

The main package surface is:

- `autoweave/`
  - `approvals/` human approval primitives and policy-shaped approval state
  - `artifacts/` artifact production and manifest/replay support
  - `compiler/` workflow compilation and execution planning
  - `context/` derived execution context services
  - `events/` runtime event modeling
  - `graph/` graph-backed context projection helpers
  - `memory/` runtime memory handling
  - `monitoring/` monitoring service, web app, and dashboard shell
  - `observability/` local observability plumbing
  - `orchestration/` orchestration logic and runtime coordination
  - `routing/` task/role routing behavior
  - `storage/` canonical runtime persistence services
  - `templates/` packaged project templates
  - `workers/` worker-side runtime behavior
  - `workflows/` workflow definitions and workflow lifecycle logic
- `apps/cli/`
  - `main.py` shipped CLI entrypoint
  - `bootstrap.py` project bootstrap/migration helpers
  - `validation.py` repository validation logic
- `tests/`
  - packaging, CLI, runtime, orchestration, storage, observability, monitoring, and queue coverage

## Public Python Surface

The top-level package currently exports:

- `build_local_runtime`
- `bootstrap_project`
- `migrate_project`
- `load_env_map`
- `LocalEnvironmentSettings`
- `AttemptState`
- `TaskState`

That is the intended public entry surface for Python callers.

## CLI Entry Points

The installed console script is:

```bash
autoweave
```

It resolves to:

```bash
python -m apps.cli.main
```

Available commands in the current CLI include:

- `status`
- `validate`
- `bootstrap`
- `migrate-project`
- `create-agent`
- `doctor`
- `run-example`
- `run-workflow`
- `worker`
- `ui`
- `cleanup-local-state`
- `new-project`

## Common Local Workflows

### 1. Install for development

```bash
python -m pip install -e .[dev]
```

### 2. Validate a local AutoWeave project

```bash
autoweave validate --root .
```

### 3. Bootstrap packaged project files into a repo

```bash
autoweave bootstrap --root .
```

### 4. Check environment and runtime wiring

```bash
autoweave doctor --root .
```

### 5. Run the local monitoring UI

```bash
autoweave ui --root . --host 127.0.0.1 --port 8765
```

### 6. Run the example flow

```bash
autoweave run-example --root . --dispatch
```

### 7. Run a real workflow request

```bash
autoweave run-workflow --root . --request "Review the backend contract and propose the next steps"
```

### 8. Run queue-backed execution instead of inline execution

```bash
autoweave run-workflow --root . --request "Ship the task board cleanup" --dispatch --queue
autoweave worker --root .
```

### 9. Clean stale local runtime state

```bash
autoweave cleanup-local-state --root .
```

## Operator Loop

If you are working across both repos, the common loop is:

1. Change execution/runtime behavior here in `Autoweave Library`.
2. Install the updated package into the web/backend environment.
3. Verify the product still consumes the library through its installed package boundary.
4. Validate both the library runtime behavior and the web product surfaces that depend on it.

For library-only validation, the fastest checks are usually:

```bash
./.venv/bin/python -m pytest tests -q
autoweave doctor --root .
autoweave ui --root . --host 127.0.0.1 --port 8765
```

## Bootstrap and Template Model

This repo ships packaged templates for AutoWeave projects.

That means:

- the sample project is not meant to live as committed mutable root state in this library repo
- instead, template-managed files are generated into a target project explicitly
- `bootstrap` creates missing project fixtures
- `migrate-project` refreshes template-managed files to newer packaged defaults
- `new-project` creates a new AutoWeave-ready project skeleton with `.env.local`, docs, and git init

## Monitoring UI

The monitoring UI belongs to the library and is intentionally lightweight.

It lives under:

- `autoweave.monitoring`

The CLI serves it through:

```bash
autoweave ui --root .
```

The monitoring layer is for runtime introspection, not for the full collaborative product shell. It helps you inspect:

- workflow runs
- tasks
- attempts
- events
- human requests
- approval requests
- artifacts
- snapshot/health state

## Queue and Worker Model

AutoWeave supports inline local execution and queue-backed execution.

Queue-backed flow currently uses Celery:

- `autoweave run-workflow --queue` enqueues a workflow
- `autoweave worker --root .` runs the worker
- queue and result wiring are configured through the local runtime environment

This is the current durable execution backbone used by the broader product integration.

## Environment Expectations

The runtime expects a project root with an AutoWeave-style config and env layout.

Common settings in local development include:

- Vertex AI project and credentials
- Postgres URL
- Redis URL
- Neo4j URL and credentials
- artifact store URL
- OpenHands agent server base URL
- backend selections such as canonical store / graph backend

The easiest way to get the expected shape is:

```bash
autoweave new-project /path/to/project
autoweave bootstrap --root /path/to/project
```

## Packaging

Build a wheel locally with:

```bash
python -m pip wheel --no-build-isolation --wheel-dir dist .
```

Build a source distribution with:

```bash
python -m build --sdist
```

The packaging boundary matters because downstream consumers, including AutoWeave Web, should use the installed package rather than direct source-tree coupling.

When you change the public runtime contract, treat packaging as part of the feature, not as a release afterthought.

## Test Coverage

The repo currently includes tests for:

- CLI behavior
- project bootstrap and migration
- packaging/public package surface
- orchestration and runtime behavior
- storage durability and service wiring
- monitoring snapshots
- local observability
- Celery queue integration
- template correctness

Run the suite with:

```bash
./.venv/bin/python -m pytest tests -q
```

## First-Time Reader Summary

If you are new to this repo, the shortest correct mental model is:

- this is the runtime engine
- it compiles and runs workflows
- it owns canonical execution state
- it can pause for approvals and clarifications
- it emits artifacts and observability data
- it can run inline or through Celery
- it ships a lightweight monitoring UI
- the web product sits above it and should consume it through the installed package boundary
