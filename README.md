# AutoWeave

AutoWeave is a terminal-first orchestration library. It owns canonical workflow state, DAG scheduling, approvals, artifact routing, context retrieval, model routing, and observability. OpenHands is the worker runtime. PostgreSQL is canonical truth. Redis is ephemeral coordination. Neo4j is a projection/query layer. Vertex AI is the model platform.

## Local architecture

- Neon Postgres stays remote and canonical.
- Neo4j Aura stays remote and non-authoritative.
- Vertex AI stays remote.
- Redis, OpenHands Agent Server, local artifact storage, and the AutoWeave runtime container run locally through Docker Compose.
- Workers use isolated per-attempt workspaces under `workspaces/`.

## Environment

Use `.env.local` for local development. Required values:

- `VERTEXAI_PROJECT`
- `VERTEXAI_LOCATION`
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

Copy the Vertex service-account JSON to `config/secrets/vertex_service_account.json`. Keep `.env.local` and `config/secrets/` out of git.

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
```

`run-example --dispatch` uses the built-in notifications-settings workflow example. It will exit non-zero if the worker run fails. In the current validation environment, the local OpenHands path reaches Vertex successfully; the remaining live limitation is runtime quality under external Vertex behavior such as rate limiting or long-running conversations.

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

After running the command, follow the instructions to complete the setup.

```bash
mkdir -p /tmp/autoweave-demo-project/docs /tmp/autoweave-demo-project/config/secrets
cp docs/autoweave_high_level_architecture.md /tmp/autoweave-demo-project/docs/
cp docs/autoweave_implementation_spec.md /tmp/autoweave-demo-project/docs/
cp docs/autoweave_diagrams_source.md /tmp/autoweave-demo-project/docs/
cp config/secrets/vertex_service_account.json /tmp/autoweave-demo-project/config/secrets/vertex_service_account.json
cp .env.local /tmp/autoweave-demo-project/.env.local
```

Then bootstrap and run the installed CLI:

```bash
/tmp/autoweave-demo-venv/bin/autoweave bootstrap --root /tmp/autoweave-demo-project
/tmp/autoweave-demo-venv/bin/autoweave validate --root /tmp/autoweave-demo-project
/tmp/autoweave-demo-venv/bin/autoweave doctor --root /tmp/autoweave-demo-project
/tmp/autoweave-demo-venv/bin/autoweave run-example --root /tmp/autoweave-demo-project --dispatch
```

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
