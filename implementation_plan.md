# AutoWeave Implementation Plan

## Status snapshot

- M0 through M5 are implemented for the deterministic local slice.
- M6 upgraded the repo from deterministic slice to a locally runnable development baseline.
- Neon Postgres and Neo4j Aura should be consumed from env, while Redis, artifact storage, and OpenHands Agent Server should run locally through Docker Compose.
- The current implementation uses the shared protocol layer to keep room for real Postgres, Redis, Celery, Neo4j, OpenHands, and Vertex-backed adapters.
- M7 through M9 are now implemented for the durable local-runtime pass.
- Native repo validation and packaged fresh-install validation both completed successfully against the real local/remote environment mix.
- Vertex IAM is now fixed and direct Vertex calls succeed.
- M10 is now implemented for the Vertex/OpenHands stabilization pass: the worker path no longer loops on repeated empty model responses.
- The current live limitation is external Vertex capacity behavior: the patched worker path now either progresses normally or exits once through the existing timeout/finalization path if Vertex leaves the conversation running or returns rate-limit pressure.

## Milestones

### M0. Bootstrap and planning

- Read and verify the design docs from `docs/`.
- Create `AGENTS.md`, `context.md`, `implementation_plan.md`, `task_list.md`, and `.env.example`.
- Establish package layout, ownership boundaries, and test harness foundation.

### M1. Domain and config foundation

- Implement typed domain models, enums, identifiers, and state machines.
- Implement canonical config schemas/loaders for agents, workflows, runtime, storage, Vertex, and observability.
- Add validation, cycle detection inputs, and example workflow configuration fixtures.

### M2. Workflow engine and orchestration

- Implement workflow parser, DAG builder, revision-aware scheduler, readiness evaluator, and orchestrator service.
- Implement human-in-the-loop state transitions and approval lifecycle orchestration.
- Add the example notifications workflow execution path.

### M3. Storage, artifacts, and memory

- Implement repository interfaces and in-memory/test-backed adapters for Postgres-owned entities.
- Implement Redis lease and idempotency abstractions and Celery task contracts.
- Implement artifact registry, visibility resolver, memory retrieval interfaces, and Neo4j projection contracts.

### M4. Worker runtime and compiler

- Implement model routing, canonical-to-OpenHands config compilation, worker adapter interfaces, remote worker dispatch scaffolding, and workspace lifecycle policies.
- Add Vertex AI environment compilation and credential-boundary-safe wiring.

### M5. Observability, CLI, and end-to-end coverage

- Implement normalized events, trace correlation helpers, metrics hooks, replay/debug metadata, and product-facing query/stream abstractions.
- Implement terminal CLI entrypoints, config bootstrap helpers, and sample agents/workflow files.
- Run full unit and integration suite for the implemented slice and stop before live credential-dependent tests.

### M6. Local runtime hardening

- Normalize `.env.local` and `.env` loading and central runtime settings resolution.
- Relocate Vertex credentials into `config/secrets/vertex_service_account.json` and normalize both canonical and worker-side credential envs.
- Add Docker Compose for local Redis, OpenHands Agent Server, and filesystem-backed artifact storage.
- Add service-backed local adapters or connection wiring for Neon/Postgres, Neo4j Aura, Redis, artifact storage, and OpenHands runtime configuration.
- Expand tests to cover env resolution, service wiring contracts, and local runtime bootstrap behavior.
- Verification result:
  - local Docker Compose stack starts cleanly
  - `autoweave doctor --root .` reports healthy local services with redacted targets
  - `autoweave run-example --root .` and `autoweave run-example --root . --dispatch` complete against the local agent-server bootstrap path

### M7. Durable storage and orchestration runtime

- Implement real Postgres-backed canonical repositories and event persistence for workflow definitions, runs, tasks, attempts, approvals, artifacts metadata, and scoped decision/memory records that are already in phase scope.
- Implement Redis-backed coordination for leases, heartbeats, queue markers, and dispatch idempotency without making Redis canonical.
- Implement real Neo4j-backed projection/query support that projects from canonical events/state and never overrides Postgres truth.
- Replace transient `WorkflowRunState` bootstrap in the local runtime with a durable orchestration service that loads and mutates canonical state through repositories.
- Verification result:
  - canonical workflow/task/attempt state persists across runtime restarts in Neon Postgres
  - Redis loss does not erase canonical workflow state
  - Neo4j disagreement is observable but does not mutate canonical truth

### M8. OpenHands lifecycle, artifacts, and recovery

- Complete the OpenHands execution path with durable dispatch, progress capture, artifact harvesting, timeout/crash handling, and authoritative attempt/task/workflow finalization.
- Keep one isolated workspace per task attempt by default and enforce resume policy explicitly.
- Emit normalized events, traces, metrics, and replay artifacts with correlation IDs for the full attempt lifecycle.
- Verification result:
  - a real local task can be dispatched through AutoWeave to the local OpenHands agent-server
  - artifacts are harvested to local storage and metadata is persisted canonically
  - failure and timeout paths leave recoverable durable state

### M9. Local runtime productization and packaged validation

- Add the AutoWeave runtime/app container to Docker Compose with health checks, startup ordering, mounted workspaces, local artifact volume, and env-file loading.
- Add end-to-end CLI/runtime flows that work both from the repo and from a packaged install in a clean environment.
- Produce/update practical docs for local runtime, testing, and fresh-project usage.
- Verification result:
  - native repo runtime test passes against the Dockerized local stack
  - packaged wheel install works in a clean environment
  - a fresh project can be bootstrapped and run through a multi-agent workflow

### M10. Vertex worker-path stabilization

- Audit the exact OpenHands, LiteLLM, and Google/Vertex dependency versions in the live path and record the exact model/provider payload AutoWeave generates.
- Reproduce the failure directly via LiteLLM against Vertex with the same service account, model string, and runtime settings.
- Isolate streaming vs non-streaming and tools-enabled vs tools-disabled behavior, and compare that to the OpenHands conversation loop.
- Apply the narrowest correct fix: provider/model normalization, dependency pin/update, provider-specific streaming/tool flag, or empty-response guardrail.
- Verification result:
  - live OpenHands runtime now sends Vertex as `vertex_ai/<model>` with provider `VertexAI` and `reasoning_effort=none` by default unless explicitly overridden
  - OpenHands no longer spins on repeated empty responses; the prior stuck-loop symptom is replaced by normal completion or a single terminal failure path
  - repo-root `doctor` succeeds again after repairing the checked-in runtime schema/config mismatch (`celery_queue_names`)
  - repo-root `run-example --root . --dispatch` no longer loops and now fails once through the normal timeout/finalization path when the live conversation remains running

## Workstreams and ownership

### Lead agent

- Owns shared contracts, planning files, package skeleton, integration, final verification, and drift tracking.
- Owns durable-pass gap analysis, milestone integration, native runtime validation, packaged-install validation, and documentation closeout.

### Orchestration workstream

- Owns `autoweave/orchestration/` and `autoweave/workflows/`.
- Responsible for DAG compilation, scheduler/readiness logic, state machines, graph revisions, and human-in-the-loop task transitions.

### Runtime workstream

- Owns `autoweave/compiler/`, `autoweave/workers/`, and routing/runtime config wiring.
- Responsible for OpenHands adapter contracts, config compilation, sandbox/workspace lifecycle, durable dispatch/finalization, Vertex AI env mapping, and provider-specific worker-path debugging/fixes.

### Storage and memory workstream

- Owns `autoweave/storage/`, `autoweave/artifacts/`, `autoweave/context/`, `autoweave/memory/`, and `autoweave/graph/`.
- Responsible for Postgres repositories, Redis coordination, artifact metadata persistence, context resolution over durable stores, Neo4j-facing projection/query adapters, and Celery/Redis integration points.

### Observability and testing workstream

- Owns `autoweave/events/`, `autoweave/observability/`, and cross-cutting test coverage under `tests/`.
- Responsible for normalized event schema, correlation/redaction, metrics/tracing hooks, replay metadata, failure-mode test coverage, and regression tests for the Vertex empty-response path.

### CLI and developer-experience workstream

- Owns `apps/cli/`, sample configs under `agents/` and `configs/`, and environment/bootstrap docs.
- Responsible for terminal entrypoints, sample workflow assets, `.env.example`, runtime docs, and packaged fresh-install validation assets.

## Interface boundaries

### Shared contracts defined by the lead agent first

- domain models and enums in shared core modules
- repository protocols for durable state and projections
- scheduler input/output contracts
- artifact registry contract
- human-request and approval service contracts
- route selection contract
- worker adapter contract
- normalized event schema and correlation metadata

### Merge rules

- Subagents do not edit planning files except through the lead agent.
- Subagents own disjoint directories to avoid conflicts.
- Shared contract changes must land through the lead agent before dependent workstream integration.

## Parallel execution plan

### Initial split after scaffolding

- Lead agent defines shared core modules and package layout locally.
- Orchestration, runtime, storage/memory, observability/testing, and CLI/DX subagents work in parallel on disjoint directories once shared contracts exist.

### Isolation model

- Preferred isolation is one git worktree per major workstream.
- Current workspace lacks `.git`, so isolation will use separate subagent threads with strict directory ownership and lead-agent integration.

## Test plan by milestone

### M1

- unit tests for config loaders, validators, and state enums/transitions

### M2

- unit and integration tests for DAG parsing, readiness evaluation, dependency gating, cycle detection, graph revisions, branch-local blocking, and human-loop transitions

### M3

- tests for repository behavior, artifact visibility/versioning, memory typed misses, idempotency keys, lease recovery, and graph projection failure isolation

### M4

- tests for route selection auditability, compiler output, runtime env injection, workspace isolation policy, resume policy, and duplicate/failure reconciliation

### M5

- end-to-end tests for the notifications workflow, observability correlation/redaction, live event stream recovery, replay timeline reconstruction, and credential-boundary-safe integration scaffolding

### M6

- tests for `.env.local` and `.env` precedence and path normalization
- tests for Vertex credential relocation and dual env export
- tests for Neon/Postgres and Neo4j Aura connection-string resolution
- tests for Redis coordination wiring, filesystem artifact storage wiring, and OpenHands agent-server client bootstrap
- tests for local runtime composition and terminal CLI commands that exercise the wired configuration
- live local verification:
  - `docker compose up -d`
  - `python3 -m apps.cli.main doctor --root .`
  - `python3 -m apps.cli.main run-example --root .`
  - `python3 -m apps.cli.main run-example --root . --dispatch`

### M7

- repository tests for canonical Postgres persistence, restart/reload behavior, graph/task/attempt/approval/event/artifact metadata round-trips, and canonical-vs-projection disagreement handling
- Redis coordination tests for leases, heartbeats, duplicate dispatch suppression, idempotency, and recovery after expired or lost coordination state
- Neo4j projection tests for event-driven projection, query behavior, and projection failure isolation

### M8

- OpenHands adapter tests for durable dispatch, progress capture, result harvesting, timeout/crash recovery, retry policy, resume policy, and authoritative attempt finalization
- integration tests for artifact visibility, supersession safety, late human responses, blocked-branch scheduling, missing-context typed failures, and observability correlation IDs across the full attempt lifecycle

### M9

- Dockerized local runtime validation for the AutoWeave app plus Redis, OpenHands, and local artifacts
- packaging tests that build a wheel/sdist, install it into a clean environment, bootstrap a fresh project, and run a realistic workflow through the intended CLI commands

### M10

- version/config audit tests or assertions for Vertex provider/model routing
- direct LiteLLM reproduction coverage for non-streaming and streaming behavior where feasible
- regression tests for empty-response guardrails, tool-enabled/tool-disabled handling, and non-looping OpenHands failure behavior

## Credential-dependent gates

- Use the existing local env and secret material already present in the workspace rather than inventing new credentials.
- Do not emit or commit secrets while relocating the Vertex JSON file and env references.
- Prefer mocked or contract-level tests only where a live dependency is not required by the current milestone.
- This pass should consume the provided Neon, Neo4j Aura, and Vertex credentials through env/config, but must still stop short of inventing or hardcoding any new secrets.
- If a live cloud-backed validation cannot be completed from the supplied environment, the exact blocker must be recorded in `context.md` and the failing integration step must remain explicitly marked in `task_list.md`.

## Final repair-pass status

- The local runtime slice is now wired through the repository boundary and no longer depends on `WorkflowRunState.from_graph(...)` alone.
- The storage/graph wiring now resolves to the real Postgres and Neo4j backends through lazy imports so the package remains importable in a clean fresh-install smoke test.
- The durable storage surface is backed by Postgres as canonical truth, Redis for ephemeral coordination, and Neo4j for non-authoritative projection/query support.
- Validation completed successfully for:
  - storage-specific durable tests
  - packaging/fresh-install live validation
  - full `pytest -q`
  - repo-root `doctor` and `run-example --dispatch`
  - packaged `autoweave bootstrap`, `validate`, `doctor`, and `run-example --dispatch`
- The next pass focuses on the OpenHands/LiteLLM/Vertex empty-response loop now that IAM is no longer the blocking issue.
- The next pass should focus on broader live-run quality: mounting richer repo context into attempt workspaces, surfacing upstream Vertex rate-limit failures more directly than a generic poll timeout when possible, and tuning model/profile defaults after the empty-response loop fix.
