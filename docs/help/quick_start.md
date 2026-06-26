# AutoWeave: Multi-Agent Orchestration Library

**AutoWeave** is the definitive execution engine for multi-agent software engineering teams. It orchestrates specialized AI agents as a coherent, predictable team by managing workflow compilation, task graphs, queue-backed durable execution, and human-in-the-loop approvals.

Unlike traditional single-agent wrappers, AutoWeave is a **control plane**. It explicitly decouples orchestration (state, graph traversal, approvals, context injection) from the execution layer (e.g., OpenHands). 

## Core Features
- **Workflow Orchestration**: Define, compile, and execute Directed Acyclic Graphs (DAGs) of agentic tasks with dynamic fan-out.
- **Durable State**: Resume paused runs, track individual attempts, and safely persist context to PostgreSQL.
- **Human-in-the-Loop**: Built-in primitives to pause execution, request approvals, or ask humans for clarifying inputs.
- **Queue Dispatch**: Offload long-running autonomous tasks to Celery workers backed by Redis.
- **Context Management**: Layered context retrieval from Artifact stores, Neo4j knowledge graphs, and vector databases.
- **Local Monitoring**: Inspect active and historic runs via a beautiful, lightweight local developer dashboard.

---

## 1. Installation

Install AutoWeave directly from PyPI. We recommend using an isolated virtual environment (`uv` or `venv`):

```bash
pip install autoweave
```

---

## 2. Quick Start: CLI Orchestration

AutoWeave provides a comprehensive CLI for local orchestration.

**Initialize a new project** in a fresh directory:
```bash
autoweave new-project
```

**Bootstrap the local environment** and configuration files:
```bash
autoweave bootstrap
```

**Start the control plane UI** and background Celery worker:
```bash
autoweave start
```
*Your UI dashboard will now be available at `http://localhost:8766`.*

**Execute a workflow** from the terminal:
```bash
autoweave run-workflow --root . --request "Create a React component for a login page"
```

---

## 3. Creating with AutoWeave (Code Examples)

AutoWeave is highly extensible. The true power lies in its programmatic Python API, where you can define custom task graphs, build specialized agent configurations, and manage human approvals natively in code.

### Example 3.1: Launching a Basic Workflow Programmatically

```python
from autoweave.orchestration.runtime import build_local_runtime

# 1. Initialize the runtime pointing to your project root
runtime = build_local_runtime(root_path="./my-weave-project")

# 2. Dispatch a new workflow to the execution queue
workflow_run = runtime.launch_workflow(
    request="Review the backend contract and propose next steps"
)
print(f"Successfully started workflow run: {workflow_run.id}")
```

### Example 3.2: Defining Custom Workflows (DAGs)

AutoWeave allows you to define complex task dependencies (DAGs) so agents can work in parallel or block until prerequisites are met.

```python
from autoweave.workflows.compiler import compile_workflow
from autoweave.models import TaskDefinition

# Define individual tasks
task_a = TaskDefinition(
    key="analyze_schema",
    description="Analyze the existing PostgreSQL schema for missing indexes.",
    agent="database_architect"
)

task_b = TaskDefinition(
    key="propose_migrations",
    description="Propose SQL migrations based on the schema analysis.",
    agent="backend_developer",
    dependencies=["analyze_schema"] # Task B waits for Task A to finish
)

# Compile them into an executable workflow DAG
workflow = compile_workflow(
    name="Database Optimization",
    tasks=[task_a, task_b]
)
```

### Example 3.3: Creating an Agent Bundle (YAML)

Agents are defined as "bundles" comprising a YAML configuration and a Markdown playbook that acts as their core system prompt.

`agents/database_architect/agent.yaml`:
```yaml
name: database_architect
description: "An expert in PostgreSQL optimization and schema design."
model: vertex_ai/gemini-pro
temperature: 0.1
tools:
  - run_sql_query
  - list_tables
```

`agents/database_architect/playbook.md`:
```markdown
# Database Architect Playbook
You are a Staff-level Database Engineer.
When analyzing schemas:
1. Always check for foreign key indexes.
2. Ensure UUIDs are used for primary keys in high-scale tables.
3. Use the `run_sql_query` tool to inspect active table constraints.
```

### Example 3.4: Human-in-the-Loop (Approvals)

AutoWeave treats human intervention as a first-class workflow object. You can inject approval gates into your task graph.

```python
from autoweave.models import ApprovalRequest, TaskDefinition

# Define a task that requires explicit human approval before dispatching
sensitive_task = TaskDefinition(
    key="execute_migrations",
    description="Run the proposed SQL migrations against production.",
    agent="backend_developer",
    requires_approval=True
)

# In your runtime polling loop, you can resolve this approval programmatically:
from autoweave.approvals.service import ApprovalService

approval_service = ApprovalService(db_path="./autoweave.db")
pending = approval_service.list_pending_approvals()

for req in pending:
    if req.task_key == "execute_migrations":
        approval_service.grant_approval(
            request_id=req.id, 
            reason="LGTM, migrating now."
        )
```

### Example 3.5: Inspecting State and History

You can query the current state of all active attempts, queued tasks, and finished workflows instantly.

```python
from autoweave.monitoring.service import MonitoringService

# Connect to the local canonical SQLite database
service = MonitoringService(db_path="./my-weave-project/autoweave.db")

# Fetch a snapshot of all active runs, queued tasks, and human requests
state_snapshot = service.snapshot(limit=5)

for run in state_snapshot.get("runs", []):
    print(f"Run ID: {run['id']} | Status: {run['execution_status']}")
```

---

## 4. Support & Architecture

For comprehensive architecture specs, deployment instructions, and advanced configuration options, visit our [GitHub Repository Documentation](https://github.com/hypnoastic/Autoweave-Library).
