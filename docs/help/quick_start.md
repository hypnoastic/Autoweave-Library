# Quick Start

Welcome to AutoWeave! This guide will help you get your first agent workflow running locally.

## 1. Initialization
First, initialize a new AutoWeave project in a fresh directory:
```bash
autoweave new-project
```

## 2. Bootstrapping
Create the required agent configurations and bootstrap the local environment:
```bash
autoweave bootstrap
```

## 3. Starting the Control Plane
Start the AutoWeave UI and Celery worker using the `start` command. This will spin up the local dashboard on `http://127.0.0.1:8766`:
```bash
autoweave start
```

## 4. Running a Workflow (CLI)
To execute a workflow, you can either trigger a pre-configured example or run a custom workflow:
```bash
autoweave run-workflow --root . --request "Create a React component for a login page"
```

## 5. Running a Workflow (Python)
You can also trigger runs natively from your own Python code:

```python
from autoweave.orchestration.runtime import build_local_runtime

runtime = build_local_runtime(root_path=".")

workflow_run = runtime.launch_workflow(
    request="Review the backend contract and propose next steps"
)
print(f"Successfully started workflow run: {workflow_run.id}")
```
