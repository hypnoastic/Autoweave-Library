# AutoWeave: Advanced Multi-Agent Orchestration

**AutoWeave** is the definitive execution engine for multi-agent software engineering teams. It orchestrates specialized AI agents as a coherent, predictable team by managing workflow compilation, task graphs, queue-backed durable execution, and human-in-the-loop approvals.

Unlike traditional single-agent wrappers, AutoWeave is a **control plane**. It explicitly decouples orchestration (state, graph traversal, approvals, context injection) from the execution layer (OpenHands). 

---

## 1. How AutoWeave Operates Under the Hood

To design effectively on AutoWeave, you must understand its architecture. AutoWeave relies on a **polyglot persistence architecture** to maintain state durably:

- **The Orchestrator (AutoWeave)**: Owns the DAG (Directed Acyclic Graph). It decides *who* runs *what* and *when*. It manages human-in-the-loop pauses and state.
- **The Executor (OpenHands)**: Runs inside isolated Docker sandboxes. It has zero knowledge of the overall workflow. It only receives a single "Attempt" instruction from AutoWeave, runs it, and returns the artifacts.
- **PostgreSQL**: The absolute source of truth. Every task attempt, workflow definition, approval request, and artifact metadata is durably stored here.
- **Redis + Celery**: Handles the distributed queue. When the Orchestrator marks a task as `ready`, it places it on the Celery queue. A background worker picks it up and executes it via OpenHands.

This separation ensures that if an agent crashes or hits a rate limit, the workflow is not lost. The orchestrator simply retries the attempt or pauses for human intervention.

---

## 2. Project Directory Structure

When you initialize and bootstrap a new project via the CLI, AutoWeave generates a highly structured workspace.

```bash
autoweave new-project
autoweave bootstrap
```

This creates the following directory structure:

```text
.
├── .env.local                    # Environment variables (DB credentials, Redis URLs)
├── agents/                       # The core definitions of your AI team
│   ├── backend/                  # (Example) Backend Engineer Agent
│   │   ├── autoweave.yaml        # Core configuration (model, temperature, tools)
│   │   ├── playbook.yaml         # The Agent's operational playbook
│   │   ├── soul.md               # The Agent's persona and core directives
│   │   └── skills/               # Markdown files defining specific agent skills
│   ├── frontend/
│   ├── manager/
│   └── reviewer/
├── configs/                      # Global AutoWeave configurations
│   ├── routing/                  # Model routing profiles (e.g., fallback to Gemini Pro)
│   ├── runtime/                  # Postgres, Redis, Vertex AI connection configs
│   └── workflows/                # Task DAG definitions (e.g., team.workflow.yaml)
└── config/secrets/               # Place your Vertex AI or AWS credentials here
```

---

## 3. Designing on AutoWeave (Best Practices)

When designing a system on AutoWeave, follow these core principles:

1. **Granular Agents, Not God Agents**: Do not create a single "Full Stack Developer" agent. Create a `frontend_dev`, a `backend_dev`, and a `qa_reviewer`. Give each a hyper-specific `playbook.yaml` and `soul.md`.
2. **Explicit Task Dependencies**: Use the workflow DAG to enforce order. The `frontend_dev` task should explicitly list the `backend_dev` task as a dependency so it doesn't start until the backend API contracts are finalized.
3. **Fail Fast & Escalate**: If an agent is confused, it shouldn't guess. Design your agents' playbooks to explicitly fail the task or request human clarification using the built-in Human-in-the-Loop primitives.

---

## 4. Deep Dive: Defining an Agent

Agents are defined as "bundles" inside the `agents/` directory.

### `autoweave.yaml` (The Configuration)
Defines the technical parameters of the agent.
```yaml
name: backend_architect
description: "An expert in PostgreSQL optimization and schema design."
model: vertex_ai/gemini-pro
temperature: 0.1
tools:
  - run_sql_query
  - list_tables
```

### `soul.md` (The Persona)
The absolute core directives that govern the agent's behavior.
```markdown
# Soul: Backend Architect
You are a Staff-level Database Engineer.
You prioritize data integrity above all else. You never run destructive migrations (`DROP TABLE`) without requesting human approval first.
```

### `playbook.yaml` (The Operational Guide)
Specific steps the agent should follow when executing tasks.
```yaml
instructions:
  - "When analyzing schemas, always check for foreign key indexes."
  - "Ensure UUIDs are used for primary keys in high-scale tables."
  - "Use the `run_sql_query` tool to inspect active table constraints."
```

---

## 5. Deep Dive: Defining a Workflow

Workflows map out the Directed Acyclic Graph (DAG) of tasks. You can define this in `configs/workflows/team.workflow.yaml`:

```yaml
name: "Full Stack Feature Implementation"
tasks:
  - key: analyze_schema
    description: "Analyze the existing PostgreSQL schema."
    agent: backend_architect
    
  - key: propose_migrations
    description: "Propose SQL migrations based on the schema analysis."
    agent: backend_architect
    dependencies: 
      - analyze_schema

  - key: implement_frontend
    description: "Build the React components utilizing the new API."
    agent: frontend_dev
    dependencies:
      - propose_migrations
```

AutoWeave will automatically parse this YAML, insert it into PostgreSQL, and ensure `implement_frontend` remains `blocked` until `propose_migrations` reaches a `completed` state.

---

## 6. Programmatic Control Plane API

You can bypass the CLI and trigger these workflows entirely via Python.

### Launching a Workflow
```python
from autoweave.orchestration.runtime import build_local_runtime

runtime = build_local_runtime(root_path="./my-weave-project")

# AutoWeave reads `configs/workflows/` and executes the DAG
workflow_run = runtime.launch_workflow(
    request="Review the backend contract and propose next steps"
)
print(f"Started run: {workflow_run.id}")
```

### Handling Human-in-the-Loop Approvals
If a task is marked as `requires_approval: true`, the orchestrator pauses that specific branch of the DAG.
```python
from autoweave.approvals.service import ApprovalService

approval_service = ApprovalService(db_path="./autoweave.db")
pending = approval_service.list_pending_approvals()

for req in pending:
    # Programmatically grant approval, unlocking the task queue
    approval_service.grant_approval(
        request_id=req.id, 
        reason="LGTM, migrating now."
    )
```

---

## 7. Installation & Monitoring

Install the library:
```bash
pip install autoweave
```

Start the built-in monitoring dashboard to trace agent executions, view generated artifacts, and resolve human-in-the-loop approvals visually:
```bash
autoweave ui --root ./my-weave-project
```
Then navigate to `http://localhost:8766` in your browser.
