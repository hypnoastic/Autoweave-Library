# AutoWeave Context

## Project purpose

AutoWeave is a terminal-first, library-first multi-agent orchestration control plane. It owns canonical workflow state, task DAG scheduling, approvals, human-in-the-loop handling, artifact routing, context and memory services, model routing, and observability. OpenHands is the remote worker runtime for single-task execution inside isolated sandboxes. Vertex AI is the target model platform.

## Design-doc summary

### Architecture summary

- AutoWeave is the only orchestration authority.
- OpenHands agent-server remote workers are the production execution path.
- AutoWeave owns canonical agent, workflow, task, artifact, context, and runtime schema and compiles worker-facing config just in time.
- PostgreSQL is the durable source of truth. Redis handles ephemeral coordination, leases, and heartbeats. Celery handles async orchestration jobs. Neo4j is an asynchronous projection and graph-query surface, not canonical truth.
- Workers retrieve scoped context through AutoWeave tools and services rather than direct database access or giant context dumps.
- The default workspace policy is one isolated sandbox/worktree per task attempt, reused only for resume of the same attempt when healthy.
- Artifacts are published to an orchestrator-owned registry and exposed to downstream tasks according to dependency and policy rules.
- Human clarification and approval are first-class workflow objects; workers can request changes, but only the orchestrator mutates authoritative task and workflow state.
- Observability must be exported as normalized AutoWeave events, traces, metrics, and replay artifacts rather than exposing raw OpenHands internals directly to the main product.

### Implementation summary

- The repository needs canonical config loaders for agents, workflow definitions, runtime, storage, Vertex, and observability settings.
- The core domain model includes project/team/agent/workflow/task/attempt/artifact/decision/memory/human-request/approval/event/model-route/workspace entities with explicit task and attempt state machines.
- The scheduler must support DAG readiness evaluation, dynamic graph revisioning, fan-out of independent tasks, and branch-local blocking behavior.
- Context services need typed retrieval and typed miss responses, plus structured writeback for artifacts, decisions, blockers, approvals, and summaries.
- The worker adapter must compile canonical config into OpenHands-facing config, inject Vertex credentials, provision remote sandboxes, stream events, and finalize attempts idempotently.
- Tests must cover workflow scheduling, human-loop safety, artifact visibility, duplicate delivery, lease recovery, graph projection failure, route auditing, worktree isolation, and observability correlation/redaction.

### Diagram summary

- The diagrams reinforce the same split across control plane, worker plane, storage plane, and observability plane.
- The example workflow is manager -> backend contract/frontend UI in parallel -> backend implementation -> integration -> review.
- Observability, context resolution, artifact flow, and human-loop transitions are all mediated by AutoWeave services, not worker-side direct access.

## Contradiction check

One design ambiguity needs an implementation decision:

- `docs/autoweave_implementation_spec.md` describes dynamic mutation marking a running task as `blocked_by_graph_change`, but the canonical task-state list does not define `blocked_by_graph_change` as a valid task state.

Resolution for implementation:

- keep the canonical task-state enum exactly as documented
- represent graph-change blocking as task state `blocked` with a structured block reason such as `graph_change`
- emit an explicit graph-change event so the distinction remains auditable without inventing an undocumented canonical task state

## What exists already

- Root architecture documents were provided and copied into `docs/` to match the required repository structure.
- The repository now contains a typed Python package scaffold with the required module layout under `autoweave/`, terminal entrypoints under `apps/cli/`, sample agent/config fixtures under `agents/` and `configs/`, and deterministic tests under `tests/`.
- The current workspace does not contain `.git`, so git worktree isolation is not available at this stage.

## What is being built now

Current milestone: durable infrastructure and end-to-end runtime completion.

Scope in progress:
- replace in-memory canonical repositories and coordination adapters with durable implementations while preserving the current architecture
- complete the OpenHands execution lifecycle through durable attempt updates, artifact harvesting, and failure recovery
- make the local Docker runtime work end to end against remote Neon Postgres, remote Neo4j Aura, local Redis, local artifacts, local OpenHands Agent Server, and remote Vertex AI
- validate both the native repo runtime path and a packaged fresh-install demo path

## Decisions made during implementation

- The design docs under `docs/` are now treated as the source of truth.
- Because the workspace is not a git repository, safe parallelism will use explicit subagent ownership over disjoint directories instead of git worktrees until repository tooling changes.
- Planning and environment files are created before code implementation, per the startup contract.
- Dynamic graph-change blocking will use canonical task state `blocked` plus a structured block reason instead of introducing a new undocumented state enum value.
- Shared root contracts are frozen in `autoweave/models.py`, `autoweave/config_models.py`, `autoweave/protocols.py`, and `autoweave/types.py` before parallel implementation.
- Baseline packaging and shared-contract tests pass locally before workstream integration.
- The current slice uses deterministic in-memory implementations for canonical repositories, event streaming, routing audit logs, artifact visibility, and graph projection so behavior can be validated before wiring real Postgres, Redis, Celery, Neo4j, and OpenHands services.
- Local development now resolves `.env` and `.env.local` through a single settings layer, normalizes Vertex credential paths into `config/secrets/vertex_service_account.json`, and redacts secrets in diagnostic output.
- Local Docker infrastructure now runs Redis, a filesystem-backed artifact volume, and an OpenHands agent-server using the documented `ghcr.io/openhands/agent-server:latest-python` image.
- The OpenHands client now targets the official `/api/conversations` bootstrap route instead of the old placeholder path, and uses a container-visible workspace path under `/workspace/workspaces/<attempt_id>`.

## Blockers and risks

- Without git metadata, worktree-based isolation and branch-based merge tracking cannot be used in this workspace.
- The repository starts effectively empty, so core packaging, test harness, and service boundaries all need to be bootstrapped together.
- Real Postgres, Redis, Celery, and Neo4j adapters are still contract-level wiring around in-memory implementations; the repo now consumes live connection settings but does not yet persist canonical state to Neon or project graph/query state to Neo4j Aura.
- The OpenHands integration now reaches a live local agent-server for health and conversation bootstrap, but the library still stops short of full streamed execution management, result harvesting, and durable attempt finalization against real worker runs.
- Vertex-backed execution is configured and ready for the local worker runtime, but this pass intentionally did not force a full model-executing workflow run as part of automated verification.
- The Docker Compose contract is valid, but the current workspace cannot reach the Docker daemon (`unix:///Users/yashkumar/.docker/run/docker.sock`), so the native container stack could not be started here.
- A full `pytest -q` run still reports unrelated durable-storage/orchestration failures outside this Docker/runtime pass, specifically in `tests/test_orchestration.py` and `tests/test_storage_durable.py`.

## Divergence notes

- Prompt requested one worktree per major workstream where safe. Current workspace cannot support git worktrees because `.git` is absent, so isolated subagent ownership over disjoint file sets is the temporary substitute.
- The prompt and docs require production roles for Postgres, Redis, Celery, Neo4j, and OpenHands remote workers. This slice implements the contracts, deterministic in-memory behavior, and config/compiler/runtime scaffolding, but not live service-backed adapters.
- The sample workflow keeps the required dependency graph and behavior, but the `integration` task is assigned to the `backend` role in the sample fixture rather than a dedicated integration-only role.

## Milestone summary

### Workstreams used

- lead integration thread
- orchestration subagent
- runtime subagent
- storage and memory subagent
- observability and testing subagent
- CLI and developer-experience subagent

### Implemented modules

- domain and config contracts in `autoweave/models.py`, `autoweave/config_models.py`, and `autoweave/protocols.py`
- workflow parsing, graph construction, scheduler, and authoritative human/approval state handling
- config loading, Vertex route selection, OpenHands config compilation, worker env mapping, and workspace policy scaffolding
- in-memory canonical repositories, artifact visibility, context typed misses, memory store, lease/idempotency primitives, task envelopes, and graph projection backend
- normalized events, redaction, replay/cursor stream support, metrics/tracing/debug-artifact helpers
- CLI validation/bootstrap/status commands and sample `agents/` plus `configs/` fixtures

### Tests added and run

- Added: `tests/test_shared_contracts.py`, `tests/test_orchestration.py`, `tests/test_runtime.py`, `tests/test_storage_context.py`, `tests/test_observability.py`, `tests/test_cli.py`
- Ran: `pytest -q`
- Ran: `python3 -m compileall autoweave apps tests`
- Ran: repository validation through `apps.cli.validation.validate_repository(Path('.'))`
- Ran: `pytest tests/test_infra.py -q`
- Ran: `pytest tests/test_packaging.py -q`
- Ran: `pytest tests/test_local_runtime.py tests/test_cli.py -q`
- Ran: `docker compose config`
- Attempted: `docker compose up -d redis artifact-store openhands-agent-server autoweave-runtime` and hit a Docker daemon connectivity blocker

### Remaining gaps before live integration

- no real Postgres repositories or migrations yet
- no real Redis, Celery, or Neo4j client wiring yet
- no live OpenHands agent-server dispatch yet
- no real Vertex AI invocation yet
- no live SSE/WebSocket or OTLP backend verification yet
- native Docker stack validation is blocked by the unavailable Docker daemon in this workspace
- unrelated durable orchestration/storage tests still fail outside the current Docker/runtime slice

## Prompt and design comparison

Current implementation aligns with the prompt and design docs on:
- AutoWeave remaining the sole orchestration authority
- OpenHands remaining the worker runtime target
- canonical schema staying inside AutoWeave
- Postgres/Redis/Celery/Neo4j roles being separated in the contract layer
- one-workspace-per-attempt policy being encoded
- artifact visibility being orchestrator-defined
- human-in-the-loop and approval state changes staying orchestrator-authoritative
- Vertex AI credential injection being non-interactive
- normalized observability export being owned by AutoWeave

Current implementation only partially satisfies the prompt where live infrastructure is required:
- storage, coordination, and graph layers are contract-complete but in-memory
- worker dispatch now bootstraps a real OpenHands local conversation, but deeper lifecycle integration remains scaffolded
- integration tests cover local infra/bootstrap wiring, but not full Neon/Neo4j/Vertex-backed workflow persistence and execution

## Retrospective notes

- The explicit contract freeze before spawning workstreams reduced merge friction and kept module ownership clean.
- The lack of git metadata prevented true worktree isolation; if the repository is initialized later, future slices should switch to real worktrees.
- The next high-value milestone is replacing in-memory adapters with service-backed implementations behind the existing protocols and then exercising them with supplied credentials and endpoints.

## Gap analysis: 2026-03-20

- The design docs were re-read before this repair pass, along with `context.md`, `implementation_plan.md`, and `task_list.md`.
- The current codebase is coherent as a deterministic local slice, but it is not yet runnable against the intended local/remote environment mix.
- There is no central environment loader for `.env.local` or `.env`, so runtime config currently depends on ad hoc values rather than a canonical local bootstrap path.
- The Vertex service-account JSON still sits at the project root instead of `config/secrets/vertex_service_account.json`, and the code does not yet normalize both `VERTEXAI_SERVICE_ACCOUNT_FILE` and `GOOGLE_APPLICATION_CREDENTIALS` to the same local path.
- `.env.example` currently contains live-looking connection values instead of placeholder examples and should be sanitized, with real local values moving into a gitignored env file.
- There is no Docker/Docker Compose setup yet for the required local services: Redis, OpenHands Agent Server, and local artifact storage.
- Storage and runtime adapters are still mostly in-memory or scaffolding-only. There is no real Neon/Postgres connection wiring, Neo4j connection wiring, Redis-backed coordination client, filesystem-backed artifact store, or OpenHands agent-server HTTP client.
- There is no single terminal-first runtime bootstrap that composes configs, env, repositories, artifact storage, observability, scheduler, and worker adapter into a locally runnable entrypoint.
- The test suite is green, but it does not yet cover env-file resolution, credential-path relocation, live-config normalization, Docker-facing assumptions, or remote-service wiring contracts for Neon/Neo4j/OpenHands.

## Gap analysis: 2026-03-24 monitoring-UI pass

- The repository is still fundamentally terminal-first and library-first, but there is no dedicated monitoring surface for watching active workflow runs, task state, attempts, artifacts, or human blockers in one place.
- The current CLI entrypoints are functional, but they do not provide a dedicated debug/monitoring view; the only way to inspect runs is through terminal summaries or by reading storage directly.
- The storage layer can already read most canonical state for a workflow run, but it does not yet expose a concise read-only catalog of recent runs for a dashboard.
- The repository root still mixes library code, sample project fixtures, and demo-validation assets closely enough that a clear monitoring surface is the most useful separation point for this pass.
- This pass needs to add a lightweight local UI that can be launched from a command, accept a user request, and display canonical state without introducing a heavy frontend stack or changing the orchestrator boundary.

## Repair pass summary: 2026-03-20

- Added `autoweave/settings.py` as the canonical local-development settings layer, with `.env` and `.env.local` precedence, canonical Vertex credential relocation, connection-target parsing, and redacted diagnostics.
- Copied the existing Vertex service-account JSON into `config/secrets/vertex_service_account.json`, normalized `.env.local` to point both `VERTEXAI_SERVICE_ACCOUNT_FILE` and `GOOGLE_APPLICATION_CREDENTIALS` at that path, sanitized `.env.example`, and expanded `.gitignore` to keep local env files, secret files, and runtime state out of version control.
- Added `docker-compose.yml` for local Redis, filesystem-backed artifact storage, and a healthy OpenHands agent-server using `ghcr.io/openhands/agent-server:latest-python`.
- Added `autoweave/storage/wiring.py` and `autoweave/artifacts/filesystem.py` so the local runtime composes filesystem-backed artifacts, local observability sinks, in-memory canonical contracts, and explicit Neon/Neo4j/Redis connection targets from a single entrypoint.
- Updated `autoweave/local_runtime.py` and `apps/cli/main.py` so `doctor` and `run-example` use the real local composition root, the CLI works under `python -m apps.cli.main`, and local diagnostics no longer leak database or graph passwords.
- Replaced the placeholder OpenHands bootstrap route with the live `/api/conversations` API, aligned the payload to the OpenHands SDK OpenAPI schema, switched worker launch paths to container-visible `/workspace/workspaces/<attempt_id>` locations, and verified dry-run plus live bootstrap against the local agent-server.
- Expanded tests for env resolution, Vertex credential normalization, Docker Compose contract, CLI module entrypoint behavior, storage/observability wiring, redacted diagnostics, and OpenHands conversation bootstrap translation.
- Added a dedicated `autoweave-runtime` Docker service, a `Dockerfile`, `.dockerignore`, and a `README.md` runbook so the local stack is runnable in Docker alongside Redis and OpenHands.
- Added packaging/demo coverage that builds a wheel, installs it into a clean venv, bootstraps a fresh project layout, and exercises `bootstrap`, `validate`, `doctor`, and `run-example --dispatch` against a local fake OpenHands endpoint.

## Remaining work after this pass

- Replace the in-memory canonical repositories and coordination primitives with real Neon/Postgres, Redis, Celery, and Neo4j-backed adapters behind the existing protocols.
- Extend the OpenHands integration from conversation bootstrap to full run lifecycle management, event streaming, artifact/result harvesting, and authoritative attempt finalization.
- Add credential-backed integration coverage that exercises real Vertex model execution and persistent state updates once the next implementation slice is authorized.

## Gap analysis: 2026-03-20 durable infrastructure pass

Already implemented:

- typed domain/config contracts, DAG compilation, scheduler logic, human-loop transitions, route selection, OpenHands config compilation, terminal CLI commands, local env normalization, local Docker infra baseline, and deterministic tests
- local filesystem artifact payload storage, JSONL observability, and a real OpenHands health/bootstrap client

Still stubbed or in-memory:

- the durable pass is currently using SQLite-backed surrogates for canonical persistence and graph projection, which does not satisfy the explicit Neon Postgres and Neo4j Aura requirement
- `autoweave/storage/repositories.py` still exposes only `InMemoryWorkflowRepository` for the repository protocol surface, while the real Postgres-backed repository still needs to own canonical truth
- `autoweave/storage/coordination.py` still needs to be exercised as the durable Redis coordination path for actual lease/idempotency behavior in the live runtime
- `autoweave/graph/projection.py` still needs the real Neo4j-backed adapter path rather than a local surrogate implementation
- `autoweave/context/service.py` still resolves context through repository and memory abstractions that need to be validated against the Postgres-backed store
- `autoweave/storage/tasks.py` defines Celery-shaped envelopes, but not a live Redis/Celery-backed dispatch path

Broken or incomplete for the intended architecture:

- `autoweave/storage/wiring.py` must be aligned to the real Postgres repository and Neo4j projection classes, not the SQLite placeholders
- the current storage tests still assume the SQLite-class names in a few places and need to be switched to the real repository/projection implementations
- the repo still needs the durable Postgres/Neo4j-backed validation path exercised against the supplied Neon and Aura endpoints
- the OpenHands runtime still needs durable attempt finalization and result harvesting once the storage slice is fully wired
- the repo still needs package build/install and fresh-project execution validation after the durable storage slice is updated

What this pass needs to build:

- Postgres-backed canonical repositories for workflow definitions, workflow runs, tasks, attempts, approvals, events, artifacts metadata, and phase-appropriate decision/memory records using the psycopg/SQLAlchemy stack
- Redis-backed leases, heartbeats, queue markers, and dispatch idempotency
- Neo4j-backed projection/query support that never overrides Postgres truth
- a persistent orchestration/runtime service that loads state from Postgres, coordinates through Redis, projects to Neo4j, stores artifact payloads locally, and emits normalized observability
- a completed OpenHands attempt runner with dispatch, progress capture, artifact harvesting, durable attempt/task/workflow updates, and recoverable error handling
- Docker Compose support for the AutoWeave runtime service in addition to Redis, OpenHands, and local artifact storage

## Vertex empty-response debugging pass: 2026-03-20

### Focused debugging plan

- audit the exact live versions and the exact AutoWeave -> OpenHands request payload
- reproduce the failure outside OpenHands through LiteLLM + Vertex directly
- isolate streaming, native tool-calling, and reasoning settings
- apply the narrowest provider-specific fix rather than broad retries or architecture changes
- rerun the direct path, the OpenHands path, and the repo-root CLI path before closing the pass

### What was already implemented before the fix

- AutoWeave already routed Vertex through the canonical provider/model path and normalized OpenHands model identifiers to `vertex_ai/<model>`
- the local Dockerized runtime stack, durable storage path, and OpenHands `/api/conversations` bootstrap path were already working
- Vertex IAM had already been repaired, and direct raw Vertex calls were returning `200`

### What was broken

- the live OpenHands conversation path could start successfully and then get stuck in a loop of empty assistant turns
- the failing replay showed OpenHands receiving `model=vertex_ai/gemini-2.5-flash`, `stream=false`, `native_tool_calling=true`, and `reasoning_effort=medium`
- the conversation replay then contained repeated assistant `MessageEvent`s with empty content and no tool calls before the execution status became `stuck`
- the repo-root CLI path also had an unrelated bootstrap bug: the checked-in `configs/runtime/runtime.yaml` declared `celery_queue_names`, but `RuntimeConfig` still rejected that field, so the live runtime could fail before reaching OpenHands

### Root cause

- the empty-response loop was caused by the Vertex/OpenHands worker path defaulting to reasoning-enabled requests (`reasoning_effort=medium`) for Gemini tool runs
- in the failing path, Vertex/LiteLLM/OpenHands could emit an assistant turn with no text and no tool calls; OpenHands treated that as a normal loop step rather than a terminal/provider-specific failure, so the conversation kept polling until it became `stuck`
- the evidence is strongest in the captured live replay and OpenHands logs; the direct LiteLLM reproduction also showed the same structural failure earlier in the session on a tool-continuation request, although later reruns were not fully deterministic
- streaming was not the active trigger in the failing live path because the captured OpenHands request already had `stream=false`

### Exact versions and payload verified in the live path

- OpenHands SDK in the live container: `1.14.0`
- LiteLLM in the live container: `1.80.10`
- live OpenHands image digest observed during this pass: `sha256:38792ff052a0e3ab0511ac3ba3905817aa8ff23673f1e591ec542a8219f50b9d`
- host-side supporting libraries observed during this pass:
  - `litellm==1.80.10`
  - `google-auth==2.49.1`
  - `openai==2.29.0`
  - `requests==2.32.5`

Verified failing-path payload before the fix from the stored replay artifact:

- provider: `VertexAI`
- model sent to OpenHands/LiteLLM: `vertex_ai/gemini-2.5-flash`
- `stream=false`
- `native_tool_calling=true`
- `reasoning_effort=medium`

Verified live payload after the fix from the new repo-root run:

- provider: `VertexAI`
- model sent to OpenHands/LiteLLM: `vertex_ai/gemini-2.5-pro`
- `reasoning_effort=none`
- no repeated `LLM produced empty response` warnings in the observed OpenHands logs for the patched run

### What changed in this pass

- `autoweave/workers/runtime.py`
  - added provider-aware `resolve_openhands_reasoning_effort(...)`
  - defaulted Vertex/OpenHands requests to `reasoning_effort=none` unless explicitly overridden by runtime policy
  - preserved explicit overrides so the behavior remains auditable and opt-in
  - enriched normalized `MessageEvent` payloads with `reasoning_content_present` so reasoning-only empty turns remain diagnosable in replay artifacts
- `autoweave/local_runtime.py`
  - propagated the safe Vertex runtime default (`reasoning_effort=none`) into the composed runtime policy
  - improved the empty-response-loop diagnostic rewrite so reasoning-only empty turns are called out explicitly instead of surfacing as a generic stuck run
- `autoweave/config_models.py`
  - added `celery_queue_names` to `RuntimeConfig` so the checked-in runtime YAML can bootstrap the real CLI path again
- `tests/test_runtime.py`
  - added regression coverage for Vertex reasoning defaults, explicit reasoning overrides, reasoning-only empty `MessageEvent`s, and runtime config acceptance of declared Celery queues
- `tests/test_local_runtime.py`
  - asserted that the composed local runtime now sends `reasoning_effort=none` for Vertex/OpenHands requests

### Proof of fix

- direct Vertex itself still works normally with the same service account and project/location settings
- direct LiteLLM control calls with Vertex now complete normally in the non-streaming path under the patched configuration
- `python -m apps.cli.main doctor --root .` succeeds again after the runtime-schema repair
- `python -m apps.cli.main run-example --root . --dispatch` no longer exhibits the old empty-response loop; the patched repo-root run now exits once through the normal timeout/finalization path with:
  - `failure_reason=conversation poll timed out after 90.0s`
  - durable task state `blocked`
  - durable attempt state `orphaned`
- the new replay artifact for the patched run records `reasoning_effort=none` and does not contain the prior `empty_response` loop signature

### Remaining limitations after the fix

- the repo-root live example is not yet achieving a clean successful completion; the current live run remains sensitive to external Vertex runtime behavior, including observed `429 RESOURCE_EXHAUSTED` pressure in the OpenHands container logs
- the manager task still enters a very minimal isolated workspace, so the live example does not yet give the worker a richer seeded repo snapshot or narrower startup instructions
- the direct LiteLLM empty-turn reproduction was not perfectly deterministic across repeated reruns, so the strongest evidence remains the captured failing replay plus the observed elimination of the loop after the provider-specific reasoning default changed

## Gemini 3 migration/debugging plan: 2026-03-23

- audit the current Gemini 2.5 model path end to end across AutoWeave config, router output, OpenHands request compilation, and live Vertex endpoint behavior
- verify valid current Gemini 3 family model IDs from official Vertex sources before changing defaults
- add a controlled config surface so the active local/dev Vertex profile can be switched between Gemini 2.5 fallback and Gemini 3 candidates without hardcoded hacks
- try at least one Gemini 3 Flash path first, then `gemini-3.1-pro-preview` if the stack supports it, and compare auth, empty-response behavior, rate-limit behavior, and OpenHands stability
- update tests and docs so deprecated Gemini 3 IDs are not the default and the best working profile is clearly recorded
- native runtime validation and packaged fresh-install validation that exercise the real local/remote environment mix without hardcoding secrets

## Gemini 3 migration/debugging result: 2026-03-23

### Audit findings

- The runtime source of truth for live Vertex routing is `configs/runtime/vertex.yaml`; `configs/routing/model_profiles.yaml` mirrors the same profile family for routing/diagnostics, but the OpenHands worker path ultimately follows the runtime config plus the local environment seen by the agent-server container.
- AutoWeave already normalized worker model strings correctly to `vertex_ai/<model>` in `autoweave/workers/runtime.py`, so the remaining Gemini 2.5 instability was not caused by provider-name formatting.
- The main Gemini 2.5 defaults and assumptions were spread across `configs/runtime/vertex.yaml`, `configs/routing/model_profiles.yaml`, `apps/cli/bootstrap.py`, `.env.example`, local settings defaults, and a cluster of runtime/CLI tests.
- The direct provider stack and the OpenHands stack were both capable of using Gemini 3, but only when Vertex routing used the `global` endpoint rather than the old local default of `us-central1`.

### Model and endpoint results

- Direct LiteLLM/Vertex smoke tests:
  - `vertex_ai/gemini-2.5-flash` worked against `us-central1`
  - `vertex_ai/gemini-3-flash-preview` failed against `us-central1` and succeeded against `global`
  - `vertex_ai/gemini-3.1-pro-preview` succeeded against `global`
- Direct streaming and native-tool tests also succeeded against `global` for:
  - `vertex_ai/gemini-3-flash-preview`
  - `vertex_ai/gemini-3.1-pro-preview`
- Live AutoWeave/OpenHands validation succeeded with planner routing on `vertex_ai/gemini-3.1-pro-preview` once the local runtime and agent-server container were aligned to `VERTEXAI_LOCATION=global`.

### Root cause

- The remaining Gemini 3 failure was not IAM and not bad `vertex_ai/<model>` normalization.
- In the current OpenHands/LiteLLM path, per-conversation secrets were not sufficient to change the Vertex location used by the worker runtime. The local OpenHands agent-server kept using its own process environment and continued calling `us-central1`.
- That mismatch caused Gemini 3 requests to hit the wrong Vertex endpoint and fail with model-not-found behavior even when the same model worked directly through LiteLLM against `global`.

### What changed in this pass

- Gemini 3 is now the default local/dev profile family:
  - planner: `gemini-3.1-pro-preview`
  - balanced: `gemini-3-flash-preview`
  - fast: `gemini-3-flash-preview`
- Gemini 2.5 remains available as explicit legacy fallback profiles:
  - `legacy_planner = gemini-2.5-pro`
  - `legacy_balanced = gemini-2.5-pro`
  - `legacy_fast = gemini-2.5-flash`
- `AUTOWEAVE_VERTEX_PROFILE_OVERRIDE` is now the clean config switch for forcing a specific profile without editing code.
- Local/dev defaults were aligned to `VERTEXAI_LOCATION=global` in the settings layer, Docker Compose env, sample bootstrap output, and test fixtures so the OpenHands agent-server and AutoWeave runtime agree on Vertex routing.
- Docs and tests were updated so deprecated `gemini-3-pro-preview` is not the default anywhere in the repository.

### Validated working state

- `python3 -m compileall autoweave apps tests`
- `python3 -m pytest tests/test_infra.py tests/test_settings.py tests/test_local_runtime.py tests/test_packaging.py tests/test_storage_service_wiring.py tests/test_local_observability.py -q`
- `.venv/bin/python -m apps.cli.main doctor --root .`
- direct LiteLLM smoke against `vertex_ai/gemini-3-flash-preview` on `global`
- `.venv/bin/python -m apps.cli.main run-example --root . --dispatch`
- `.venv/bin/python -m pytest -q`

The repo-root live example now completes through the real OpenHands path with:

- routed planner model `gemini-3.1-pro-preview`
- task state `completed`
- attempt state `succeeded`
- workflow still running afterward because the example only dispatches the current runnable slice
- emitted stream events and a published artifact ID

### Remaining limitations

- Gemini 3 materially improved the runtime path, but preview-model capacity behavior can still vary; `gemini-3.1-pro-preview` may still see quota or rate-limit pressure under different workloads.
- `gemini-3-flash-preview` is the lower-risk direct smoke path; the planner default remains `gemini-3.1-pro-preview` because it produced the strongest successful live AutoWeave result in this pass.
- Earlier sections in this file that mention IAM or `us-central1` Gemini 2.5 failures are historical notes; this section is the current source of truth for the Gemini migration outcome.

## Gap analysis: 2026-03-24 packaged demo pass

Already working:

- the library packages cleanly, installs into a fresh environment, boots a new project layout, validates configs, and can dispatch the built-in workflow through the local Docker stack
- local/dev Vertex routing now prefers Gemini 3 on `global`, and the repo-root live example has already succeeded through OpenHands

Still missing for the user-requested packaged demo:

- the installed CLI does not yet expose a generic "run this team request" command; `run-example` only dispatches the current workflow without an explicit user brief parameter
- the worker prompt path does not currently include `task.input_json`, so a fresh project cannot pass a structured user request into the manager task without hardcoding it in the workflow YAML
- human clarification currently depends on explicit OpenHands pause/confirmation events, which is too weak for a vague product brief demo where the manager should surface a concise clarification question back to the operator
- the sample bootstrap still assumes the default bundled roles and workflow rather than a demo-specific team with manager, backend, frontend, and tester roles plus role-local skills/docs

What this pass needs to deliver:

- a minimal generic workflow-run command for packaged installs that accepts a user request and advances the current workflow across multiple ready tasks
- prompt/input propagation so the manager task receives the user brief through canonical task state rather than ad hoc shell substitution
- a narrow human-input convention that lets the worker surface a typed clarification request instead of silently looping or succeeding with a vague plan
- a real fresh-install demo project with manager, backend, frontend, and tester agents, custom workflow/config files, the main repo env copied into the demo root, and a live run against the local Docker stack

## Final durable-runtime repair status: 2026-03-20

- `autoweave/storage/` now resolves to the real Postgres-backed canonical repository path for workflow runs, tasks, attempts, approvals, events, artifact metadata, and memory/decision records, with Redis-backed lease and idempotency coordination.
- `autoweave/graph/` now resolves to the real Neo4j-backed projection/query adapter while preserving Postgres as canonical truth. Neo4j projection is downstream-only and namespace-scoped.
- `autoweave/storage/wiring.py` now composes the real Postgres and Neo4j backends through lazy imports so the package remains importable in a clean fresh-install smoke test even when optional drivers are not present there.
- Vertex credentials stay normalized to `config/secrets/vertex_service_account.json` through both `VERTEXAI_SERVICE_ACCOUNT_FILE` and `GOOGLE_APPLICATION_CREDENTIALS`.
- The live storage slice now passes against the repository's real integration environment, and the full repository suite passes here after the storage-specific and packaging tests were updated.
- Native repo validation succeeded with `python3 -m apps.cli.main doctor --root .` and `python3 -m apps.cli.main run-example --root . --dispatch`.
- Packaged fresh-project validation succeeded from the installed artifact after bootstrapping a clean project and running the CLI smoke path there.
- An explicit live-storage integration attempt with `AUTOWEAVE_RUN_LIVE_BACKEND_TESTS=1 pytest tests/test_storage_durable.py -q` failed at DNS resolution for the Neon host in this sandbox, so live Neon/Aura proof remains blocked by environment reachability rather than repository logic.

Remaining limitation:

- live Neon Postgres and Neo4j Aura integration remains credential-bound in external environments, but the repository wiring and tests now exercise the real adapters when those services and drivers are available.

## Final validated state: 2026-03-20

This section supersedes the earlier repair-pass notes that still described Docker, durable storage, and packaged validation as incomplete.

## Gap analysis: 2026-03-20 Vertex empty-response debugging pass

- The design docs, `AGENTS.md`, `context.md`, `implementation_plan.md`, and `task_list.md` were re-read before this pass.
- Vertex IAM is no longer the blocker. The configured service account can now call Vertex successfully and the old `aiplatform.endpoints.predict` failure is gone.
- Direct Vertex `generateContent` succeeds against the configured project, region, service account, and model, which means the remaining failure is not base authentication or model reachability.
- The failing path is now specific to the OpenHands worker lifecycle. AutoWeave reaches the local OpenHands agent-server, starts a real conversation, and then the worker logs repeated `LLM produced empty response - continuing agent loop`.
- The likely fault surface is limited to model/provider normalization, the LiteLLM version OpenHands is using, Vertex streaming behavior, Vertex tool-calling behavior, or OpenHands handling of empty/tool-only assistant responses.
- The repo does not yet record the exact OpenHands/LiteLLM/runtime versions in the planning docs for this failure, and there is no regression coverage that proves direct LiteLLM behavior against Vertex or guards against the loop.
- This pass needs to establish the exact failing combination by evidence, fix the provider-specific path cleanly, and add tests so the worker either completes successfully or fails once with a precise diagnostic instead of spinning.

## Focused debugging plan: 2026-03-20

1. Record the exact OpenHands, LiteLLM, and Google/Vertex client versions in the live runtime path, plus the exact AutoWeave -> OpenHands model/provider payload.
2. Reproduce the issue outside OpenHands with the same service account, model, and provider path through LiteLLM, testing non-streaming vs streaming and tools disabled vs enabled.
3. Compare the direct LiteLLM results with the OpenHands conversation payload and event stream to isolate whether the failure is caused by provider routing, LiteLLM normalization, tool-calling, streaming, or OpenHands loop handling.
4. Patch the narrowest correct layer. Prefer fixing model/provider routing, known-bad dependency versions, or provider-specific runtime flags over broad retries or architecture changes.
5. Add regression coverage for Vertex model wiring, empty-response handling, non-streaming fallback behavior if needed, and guardrails that prevent indefinite OpenHands loops.
6. Re-run the direct Vertex/LiteLLM repro, the OpenHands path, and the AutoWeave example path, then record the root cause, working configuration, and any remaining external limitation.

### What is now implemented and working

- Neon Postgres is the active canonical repository backend in the local runtime when `AUTOWEAVE_CANONICAL_BACKEND=postgres`.
- Redis-backed lease and idempotency wiring is active for the local runtime composition.
- Neo4j Aura projection wiring is active when `AUTOWEAVE_GRAPH_BACKEND=neo4j`, while canonical truth remains in Postgres.
- The OpenHands runtime path now performs real conversation bootstrap, polls terminal conversation state, normalizes returned events, stores replay/debug payloads, publishes replay artifacts, and durably finalizes task and attempt state.
- The Postgres repository now reuses a live psycopg connection for the runtime session and batches canonical runtime writes, which removed the repeated per-write reconnection stalls seen earlier in this pass.
- The local Docker stack is working here with `redis`, `artifact-store`, `openhands-agent-server`, and `autoweave-runtime` healthy.

### Validation completed in this pass

- `docker compose build autoweave-runtime`
- `docker compose up -d redis artifact-store openhands-agent-server autoweave-runtime`
- `docker compose ps`
- `.venv/bin/python -m pytest -q`
- `AUTOWEAVE_RUN_LIVE_BACKEND_TESTS=1 .venv/bin/python -m pytest tests/test_storage_durable.py -q`
- `.venv/bin/python -m compileall autoweave apps tests build_backend.py`
- `.venv/bin/python -m apps.cli.main doctor --root .`
- `.venv/bin/python -m apps.cli.main run-example --root . --dispatch`
- packaged wheel build and fresh-install validation in `/tmp/autoweave-online-venv` and `/tmp/autoweave-online-project`
- `/tmp/autoweave-online-venv/bin/autoweave bootstrap --root /tmp/autoweave-online-project`
- `/tmp/autoweave-online-venv/bin/autoweave validate --root /tmp/autoweave-online-project`
- `/tmp/autoweave-online-venv/bin/autoweave doctor --root /tmp/autoweave-online-project`
- `/tmp/autoweave-online-venv/bin/autoweave run-example --root /tmp/autoweave-online-project --dispatch`

### Current state and remaining risk

- The IAM and wrong-endpoint blockers are resolved for the local runtime path.
- The current validated local/dev default is Gemini 3 on the Vertex `global` endpoint, with Gemini 2.5 retained as explicit fallback profiles.
- Repo-root direct smoke, OpenHands runtime validation, and `run-example --dispatch` now succeed through the live local Docker stack.
- Remaining risk is external capacity variability on preview Gemini 3 models rather than a known AutoWeave provider-routing bug.

## Packaged demo validation: 2026-03-24

What was already implemented before this pass:

- the packaged/fresh-install path already worked for `bootstrap`, `validate`, `doctor`, and the bundled `run-example` flow
- the runtime already supported real OpenHands conversations, durable Postgres state, replay artifacts, and Gemini 3 routing on Vertex `global`
- the fresh-project bootstrap still only exposed the fixed sample workflow path, and the worker prompt path did not yet carry canonical `task.input_json`

What changed in this pass:

- added a generic installed-CLI workflow execution path through `autoweave run-workflow --request ...`
- propagated canonical `task.input_json` into the compiled OpenHands launch payload and final worker prompt
- added a narrow control-marker convention so worker output beginning with `HUMAN_INPUT_REQUIRED:` or `CLARIFICATION_REQUEST:` becomes an authoritative AutoWeave human-request transition instead of plain assistant text
- added packaged-demo regression coverage for task-input propagation, clarification handling, and multi-step workflow progression
- built a clean packaged demo under `/tmp/autoweave-clothing-demo-venv` and `/tmp/autoweave-clothing-demo-project`, copied the main `.env.local`, and defined manager, backend, frontend, and tester roles plus a clothing-store workflow with role-local skill docs

Observed live packaged-demo behavior:

- packaged install succeeded from the built wheelhouse
- fresh-project bootstrap and validation succeeded after fixing one YAML quoting issue in the custom workflow
- packaged `doctor` succeeded using the copied env and normalized Vertex credentials
- the installed CLI successfully ran `run-workflow` against the live Docker/OpenHands/Vertex stack
- the manager task completed, wrote a final replay artifact, and unlocked the downstream DAG
- a three-step run dispatched `manager_plan`, `frontend_ui`, and `backend_contract` in the fresh installed project
- downstream tasks failed cleanly with durable `orphaned` attempt state plus explicit `conversation poll timed out after 15.0s` diagnostics when the shorter live poll timeout expired
- no human request was opened in the live run, which means the real Gemini path still tends to make assumptions instead of obeying the clarification contract for vague briefs

Root limitation after this pass:

- the clarification path is implemented and covered in automated tests, but live model behavior is still prompt-sensitive; the manager does not reliably ask back for missing ecommerce details unless the model chooses to follow that control-marker instruction
- this is now a model/prompt-quality limitation rather than a packaging, routing, or runtime-bootstrap failure

## Template separation: 2026-03-24

- sample-project generation has been moved behind a packaged template module at [`autoweave/templates/sample_project.py`](/Users/yashkumar/Autoweave/autoweave/templates/sample_project.py)
- [`apps/cli/bootstrap.py`](/Users/yashkumar/Autoweave/apps/cli/bootstrap.py) now delegates sample-project rendering to the packaged template module instead of owning the sample content inline
- the repo still keeps the existing root project files for compatibility, but the canonical source for bootstrap/new-project payloads is now the installed library package
- targeted CLI and packaging tests passed after the refactor
- a separate storage-context failure remains in the broader full-suite run, but it is unrelated to the template separation changes made in this pass

## Gap analysis: 2026-03-24 library-separation and monitoring UI pass

What is already in place:

- the library/runtime code is already mostly separated under `autoweave/` and `apps/cli/`
- durable workflow/task/attempt/artifact state exists behind the local runtime and canonical Postgres path
- the packaged install path works, and the installed CLI can bootstrap a project and run workflows

What is still mixed or weak:

- the repository still behaves like both the library source tree and a project instance because bootstrap/validation/default config paths assume `agents/` and `configs/` directly under the active root
- bundled sample project assets are not clearly packaged as templates distinct from the library implementation
- there is no lightweight monitoring UI for seeing the current DAG, task ownership, attempt/workspace details, artifacts, blockers, and final outputs without parsing CLI summaries
- the current `status` command does not expose enough canonical workflow state for live debugging

What this pass needs to deliver:

- keep `autoweave/` as the library and move bundled sample project assets behind an explicit project-template boundary so the library repo is not the same thing as a demo project
- add a simple local monitoring UI that can be launched from a command, submit a user request to the main workflow, and display canonical workflow runs, tasks, attempts, artifacts, and human/approval blockers
- preserve the architecture: AutoWeave remains the orchestrator, OpenHands remains the worker runtime, Postgres remains canonical truth, and the UI is only a local operator/debugging surface

Design-doc drift note for this pass:

- the implementation spec explicitly deferred a graphical product UI; this pass will add only a lightweight local monitoring/debugging surface launched by CLI command, not a full product UI or a new orchestration layer

## Monitoring UI pass summary: 2026-03-24

What changed:

- the sample project scaffold content now lives in the installed library package under `autoweave.templates.sample_project` rather than being owned inline by the CLI implementation
- bootstrap/validation still support the existing root sample layout for compatibility, but the canonical scaffold source for packaged installs is now the template module inside the library
- added a lightweight local monitoring surface under `autoweave.monitoring` that can:
  - launch a workflow from a user request
  - show the current workflow blueprint
  - show recent workflow runs from canonical storage
  - show task states, attempt states, workspaces, artifacts, human blockers, approval blockers, and recent events
  - surface the latest manager replay summary when available
- added the `autoweave ui` CLI command to start that dashboard

Validation completed in this pass:

- targeted tests for the monitoring service, WSGI dashboard app, CLI command, and packaged install path passed
- full `pytest -q` passed again after fixing an in-memory repository regression introduced by the new run-inspection list methods
- a live CLI launch of `python3 -m apps.cli.main ui --root . --port 8877` succeeded and printed the dashboard URL

Remaining limitation for this pass:

- this sandbox blocks loopback HTTP probes from a second process with `Operation not permitted`, so I could not complete a live `curl http://127.0.0.1:8877/...` check after the server bound
- the dashboard behavior itself is covered by direct WSGI tests and the CLI command launch path; the remaining limitation is sandbox networking, not the dashboard implementation

## Gap analysis: 2026-03-24 demo-agent upgrade and promptable monitor pass

What is already in place:

- packaged sample-project generation is already centralized in `autoweave/templates/sample_project.py`
- the local monitoring UI can already launch a workflow request and inspect canonical runs, tasks, attempts, artifacts, and blockers
- the installed CLI path is already capable of bootstrapping a fresh project and launching the monitor

What is still weak:

- the default packaged agents are still too generic for a realistic engineering-team demo; their souls, playbooks, and skill directories read like placeholders rather than role-specific operating guidance
- the default scaffold still uses a `reviewer` role, while the current demo intent is closer to `manager`, `backend`, `frontend`, and `tester`
- the monitoring UI is functional but still thin; it needs better visibility into agent-role assignments, the workflow task list, manager output, and produced artifacts so a human can follow what is happening without reading raw JSON or logs

What this pass needs to deliver:

- upgrade the packaged sample agents so the default bootstrap creates a more realistic delivery team with richer role guidance and real skill documents under each agent
- improve the lightweight monitor so it is practical for prompting the manager-facing workflow and tracking run/task/attempt/artifact progress live
- keep the architecture unchanged: the UI remains a local operator/debugging surface over canonical AutoWeave state, and the workflow DAG still remains orchestrator-owned

Design-doc drift note for this pass:

- the implementation spec still defers a full product GUI, so this pass will stay within a small CLI-launched local monitor rather than introducing a separate product frontend or a second orchestration layer

## Demo-agent and promptable monitor pass summary: 2026-03-24

What changed:

- the packaged sample agents now have stronger role-specific souls, playbooks, metadata, and real skill markdown files instead of placeholder-only `skills/README.md`
- the repo-root sample project was refreshed from the packaged templates, so the current `agents/` and `configs/` used by the local runtime now match the richer scaffold
- the monitor now exposes the project agent catalog in addition to the workflow blueprint, launch jobs, run steps, task assignments, attempts, artifacts, blockers, and manager summaries
- the monitor prompt copy was corrected so it no longer claims the manager mutates the canonical DAG at runtime; it now accurately describes the manager as seeding the configured workflow entrypoint while AutoWeave advances the canonical DAG
- `bootstrap --overwrite` now exists so the repo-root sample project or a local project can be resynced from the packaged templates without manual file-by-file edits

Validation completed in this pass:

- targeted scaffold, monitoring, packaging, and CLI tests passed
- full `pytest -q` passed again
- `python3 -m compileall autoweave apps tests` passed
- the local UI command started successfully and is currently serving at `http://127.0.0.1:8765`

Remaining limitation for this pass:

- the monitor is useful for prompting and observing runs, but it still does not offer an in-UI answer/resume control for human blockers; open human requests are visible and authoritative state remains orchestrator-owned
