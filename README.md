# AutoWeave

AutoWeave is a terminal-first orchestration library. It owns canonical workflow state, DAG scheduling, approvals, artifact routing, context retrieval, model routing, and observability. OpenHands is the worker runtime. PostgreSQL is canonical truth. Redis is ephemeral coordination. Neo4j is a projection/query layer. Vertex AI is the model platform.

Bundled sample project scaffolding is now treated as library-packaged template content under `autoweave.templates`, rather than being owned inline by the CLI implementation. The repo still keeps root sample assets for compatibility, but fresh-project bootstrap flows should treat the installed library package as the canonical template source.

## Local architecture

- Neon Postgres stays remote and canonical.
- Neo4j Aura stays remote and non-authoritative.
- Vertex AI stays remote.
- Redis, OpenHands Agent Server, local artifact storage, and the AutoWeave runtime container run locally through Docker Compose.
- Workers use isolated per-attempt workspaces under `workspaces/`.

## Environment

Use `.env.local` for local development. Required values:

- `VERTEXAI_PROJECT`
- `VERTEXAI_LOCATION=global` for the Gemini 3 local/dev path
- `VERTEXAI_SERVICE_ACCOUNT_FILE=./config/secrets/vertex_service_account.json`
- `GOOGLE_APPLICATION_CREDENTIALS=./config/secrets/vertex_service_account.json`
- `POSTGRES_URL`
- `REDIS_URL=redis://127.0.0.1:6379/0`
- `NEO4J_URL`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `ARTIFACT_STORE_URL=file://./var/artifacts`
- `OPENHANDS_AGENT_SERVER_BASE_URL=http://127.0.0.1:8000`
- `OPENHANDS_AGENT_SERVER_API_KEY` if required by your Agent Server
- `AUTOWEAVE_VERTEX_PROFILE_OVERRIDE` to force a specific profile such as `legacy_fast`

Copy the Vertex service-account JSON to `config/secrets/vertex_service_account.json`. Keep `.env.local` and `config/secrets/` out of git.

The checked-in Gemini 3 local/dev profile assumes the OpenHands Agent Server runs with `VERTEXAI_LOCATION=global`. OpenHands currently uses its own process environment for Vertex routing, not the per-conversation AutoWeave launch payload, so restart `docker compose up -d openhands-agent-server autoweave-runtime` after changing Vertex location values.

## Start local infrastructure

```bash
docker compose build autoweave-runtime
docker compose up -d redis artifact-store openhands-agent-server autoweave-runtime
docker compose ps
```

## Run from the repo

```bash
python3 -m pip install -e .[dev]
python3 -m apps.cli.main bootstrap --root .
python3 -m apps.cli.main validate --root .
python3 -m apps.cli.main doctor --root .
python3 -m apps.cli.main run-example --root . --dispatch
python3 -m apps.cli.main ui --root .
```

`run-example --dispatch` uses the built-in notifications-settings workflow example. It will exit non-zero if the worker run fails. In the current validation environment, the local OpenHands path reaches Vertex successfully; the remaining live limitation is runtime quality under external Vertex behavior such as rate limiting or long-running conversations.

## Monitoring UI

Launch the lightweight operator console:

```bash
python3 -m apps.cli.main ui --root . --host 127.0.0.1 --port 8765
```

The operator console lets you:

- chat with the manager-facing entrypoint to start a new run
- answer open human clarification requests inside the same run
- approve or reject approval-gated tasks without leaving the run
- inspect grouped workflow runs from canonical storage instead of a flat dump
- monitor task states, attempts, models, workspaces, artifacts, blockers, and events
- expand or collapse detailed run views progressively while keeping the main chat thread readable

The UI is intentionally lightweight and local. It is an operator/debugging surface over canonical AutoWeave state, not a second orchestrator and not a product UI.

## Agents, workflows, and autonomy

AutoWeave uses three project-owned inputs:

- `agents/<role>/autoweave.yaml`: canonical agent metadata such as tool groups, model hints, approval policy, and human interaction policy
- `agents/<role>/soul.md` and `agents/<role>/playbook.yaml`: role guidance and execution goals
- `configs/workflows/*.workflow.yaml`: canonical workflow DAG, dependencies, artifact contracts, and approval requirements

The local runtime now loads agent definitions into the real dispatch path. That means:

- model-profile hints influence routing
- allowed tool groups constrain the OpenHands launch payload
- task-template approval requirements create real approval blockers before dispatch
- answered human requests and resolved approvals resume the same canonical workflow run instead of starting over

Set `AUTOWEAVE_DEFAULT_WORKFLOW` in `.env.local` if you want the CLI and operator console to load a workflow other than `configs/workflows/team.workflow.yaml`.

## Tests

```bash
pytest -q
python3 -m compileall autoweave apps tests build_backend.py
AUTOWEAVE_RUN_LIVE_BACKEND_TESTS=1 python3 -m pytest tests/test_storage_durable.py -q
```

## Package and install

```bash
python3 -m pip wheel --no-build-isolation --wheel-dir dist .
python3 -m venv /tmp/autoweave-demo-venv
/tmp/autoweave-demo-venv/bin/python -m pip install --force-reinstall dist/autoweave-0.1.0-py3-none-any.whl
```

## New-project starter

To initialize a new AutoWeave project, run the `new-project` command:

```bash
autoweave new-project /tmp/autoweave-demo-project
```

This will create a new directory with the following structure:

- `docs/`
- `config/secrets/`
- `.env.local`
- `.gitignore`

After running the command, follow the instructions to complete the setup. The command scaffolds the expected credential path, but it does not copy live secret material into the new project.

```bash
mkdir -p /tmp/autoweave-demo-project/docs /tmp/autoweave-demo-project/config/secrets
cp config/secrets/vertex_service_account.json /tmp/autoweave-demo-project/config/secrets/vertex_service_account.json
cp .env.local /tmp/autoweave-demo-project/.env.local
```

Then bootstrap and run the installed CLI:

```bash
/tmp/autoweave-demo-venv/bin/autoweave bootstrap --root /tmp/autoweave-demo-project
/tmp/autoweave-demo-venv/bin/autoweave validate --root /tmp/autoweave-demo-project
/tmp/autoweave-demo-venv/bin/autoweave doctor --root /tmp/autoweave-demo-project
/tmp/autoweave-demo-venv/bin/autoweave run-workflow --root /tmp/autoweave-demo-project --request "Build a small clothing ecommerce storefront with a homepage, category grid, product detail page, cart handoff, and Stripe checkout." --dispatch --max-steps 6
/tmp/autoweave-demo-venv/bin/autoweave ui --root /tmp/autoweave-demo-project
```

## Cleanup local state

To wipe stale demo history and generated local residue:

```bash
python3 -m apps.cli.main cleanup-local-state --root . --all-runs
```

This purges canonical workflow runs, local artifact payloads, workspaces, caches, and other generated residue without touching tracked library code.

## Current status

Working now:

- durable Postgres-backed canonical repository path
- Redis-backed coordination wiring
- Neo4j projection wiring
- OpenHands conversation bootstrap, polling, replay artifact capture, and durable attempt/task finalization
- repo-root Dockerized local runtime validation
- packaged wheel install plus fresh-project CLI validation

Still deferred or externally blocked:

- guaranteed successful live Vertex-backed task completion under all current quota/capacity conditions
- broader Celery-dispatched background execution beyond the terminal-first runtime path
