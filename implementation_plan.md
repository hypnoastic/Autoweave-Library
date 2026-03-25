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
- M11 is now implemented for the Gemini 3 migration pass: local/dev routing now prefers Gemini 3 on the Vertex `global` endpoint while preserving explicit Gemini 2.5 fallback profiles.
- The current live limitation is external Vertex preview-model capacity variability rather than provider routing, IAM, or empty-response loop behavior.
- M12 is implemented for packaged fresh-install workflow demo validation with a custom team brief, clarification handling, and live monitoring through the installed CLI.
- M13 is now implemented for separate bundled project templates plus a lightweight monitoring UI for local workflow inspection and launch, without changing the orchestrator boundary or adding a heavy frontend stack.
- M14 is now implemented for upgrading the packaged demo-agent scaffold and making the monitor practical for live prompting and workflow observation.
- M15 is now implemented for operator-console hardening, resumable human/approval flow, runtime policy enforcement, and live dispatch coordination; the remaining drift is external OpenHands/Vertex latency during some real downstream runs.
- M16 is now implemented for screenshot-driven operator-console repair: derive operator-facing run health from canonical state, separate manager failure from manager plan rendering, redesign the details layout for laptop-width readability, and make `/api/state` non-blocking through cached asynchronous refresh.
- M17 is now active for operator-console UX cleanup: add a proper app shell and navigation, separate chat from monitoring, and reorganize workflow/task/artifact/event inspection into dedicated views.
- M18 is now active for operator-console loading and layout cleanup: remove the misleading 4-second monitor timeout, tighten sidebar scrolling, and simplify dense task-state rendering into a cleaner vertical inspection flow.

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

### M11. Gemini 3 model migration and reliability evaluation

- Audit every place where Gemini 2.5 is configured, defaulted, normalized, or assumed in the AutoWeave -> OpenHands -> Vertex path.
- Verify current supported Gemini 3 model IDs on Vertex AI from official sources before updating runtime profiles.
- Add a controlled config switch so local/dev routing can prefer Gemini 3 while retaining Gemini 2.5 as a fallback profile.
- Evaluate at least one Gemini 3 Flash path first, then `gemini-3.1-pro-preview` if supported, and compare direct LiteLLM behavior, OpenHands behavior, and repo-root example flow stability.
- Verification result:
  - model/provider routing remains `VertexAI` -> `vertex_ai/<model>`
  - deprecated Gemini 3 IDs are not the default
  - local/dev defaults now use `gemini-3.1-pro-preview` for planner and `gemini-3-flash-preview` for balanced/fast routes
  - Gemini 2.5 remains available as `legacy_planner`, `legacy_balanced`, and `legacy_fast`
  - the best available local/dev endpoint is now recorded as `VERTEXAI_LOCATION=global`
  - direct LiteLLM smoke, OpenHands runtime validation, and repo-root `run-example --dispatch` succeeded with Gemini 3
  - failures continue to surface as clear terminal diagnostics instead of empty-response loops

### M12. Packaged custom-team demo validation

- Add the smallest correct installed-CLI path for running a workflow from a user brief instead of the fixed sample description.
- Propagate canonical task input into the OpenHands prompt so the manager can see the user request without bypassing AutoWeave state.
- Add a narrow clarification convention that maps an explicit worker request into authoritative `needs_input` / `waiting_for_human` state rather than relying only on OpenHands pause events.
- Validate in a clean installed environment by creating a new project with manager, backend, frontend, and tester agents plus a demo workflow for a clothing ecommerce site.
- Verification result:
  - the packaged CLI can initialize a fresh project, validate it, and run the custom workflow from an explicit user request
  - a deliberately incomplete brief either advances through the workflow or stops with a clear human clarification request instead of silently drifting
  - the installed-project demo uses the main repo env/credentials and the existing local Docker stack

### M13. Monitoring UI and run inspection

- Treat bundled sample project assets as packaged templates rather than repo-root library state.
- Add a lightweight local UI/server that can launch a workflow from a request and render live canonical state for workflow runs, tasks, attempts, artifacts, and human blockers.
- Keep the implementation read-only with respect to orchestration state, using the existing AutoWeave runtime and storage repositories as the source of truth.
- Prefer a minimal HTML/WSGI or stdlib-based surface instead of a heavy frontend framework.
- Verification result:
  - packaged bootstrap/new-project flows work from template assets without requiring the library repo root to double as a project instance
  - the UI command can be launched from the library install
  - a request can be submitted through the UI and the resulting run inspected live
  - the dashboard shows current runs, task states, attempts, artifact outputs, and human-input/approval blockers without mutating canonical state directly
  - direct loopback probing of the bound HTTP port remains sandbox-limited in this environment, so endpoint behavior is proven here through WSGI tests plus CLI launch rather than cross-process `curl`

### M14. Demo-agent quality and promptable monitor usability

- Upgrade the packaged sample-project assets so bootstrap/new-project flows create a more realistic delivery team with richer role guidance and real skill documents.
- Align the default demo roles and workflow presentation with the current testing intent by covering manager, backend, frontend, and testing responsibilities.
- Improve the local monitor so a human can prompt the workflow and clearly inspect the current task list, role assignments, attempts, workspaces, artifacts, blockers, and latest manager output without reading raw logs.
- Verification result:
  - bootstrapped projects contain richer agent souls, playbooks, metadata, and skill documents
  - the monitor exposes the workflow blueprint, recent jobs, recent runs, and manager/task/attempt/artifact summaries clearly enough for interactive debugging
  - targeted CLI/monitor/template tests pass, full `pytest -q` passes, and the UI command can be started locally for manual use

### M15. Final hardening and operator-console completion

- Redesign the local monitor into a clearer operator console with chat-style interaction, grouped workflow runs, progressive disclosure, and explicit error states instead of indefinite loading.
- Add a resumable live workflow path so the UI can start a run, surface clarification/approval requests, accept operator responses, and continue the same canonical workflow run rather than always starting over.
- Load agent definitions into the runtime path so approval/autonomy policy, tool-group constraints, and model-profile hints become actual runtime behavior rather than static config only.
- Enforce Redis-backed lease/idempotency behavior on the live dispatch path and add regression coverage around duplicate dispatch, resume/retry, and operator-loop state transitions.
- Verification result:
  - the UI loads into a usable operator console even when runtime/storage access degrades, and it surfaces load failures clearly
  - manager chat start -> clarification/approval -> resume is supported through the UI/API and the local runtime
  - approval/autonomy policy affects dispatch/runtime behavior and appears in task/UI state
  - full `pytest -q` passes with new runtime, monitoring, and coordination coverage
  - live repo-root validation and packaged-install validation both reach the real Dockerized/OpenHands/Vertex stack with exact commands recorded
  - remaining external limitation: some downstream live tasks still hit OpenHands/Vertex timeout or generic worker-error paths, but those now finalize durably and surface clearly to the operator

### M16. Operator-console state semantics and layout repair

- Add derived operator-facing run state in the monitoring payload so the console can distinguish `active`, `waiting`, `blocked`, `stalled`, and `failed` runs without changing canonical workflow status.
- Add manager outcome fields so missing/failed manager plans are rendered as execution failures or missing plan data instead of being shown as the plan.
- Replace the narrow task-details table with a clearer card/list layout that keeps task state, attempt state, blockers, dependencies, and model/workspace metadata readable on laptop-sized screens.
- Tighten run-grouping and chat/detail summaries around derived state rather than only the coarse workflow-run status.
- Verification result:
  - screenshot-reproduced blocked/stalled runs no longer appear as if they are actively progressing
  - manager timeout text is shown as manager failure or execution note, not as the workflow plan
  - task states such as `waiting_for_dependency` remain readable without clipping
  - monitor regression tests cover derived status and the updated rendering contract
  - `/api/state` returns immediately with a cached/loading snapshot while live refresh continues in the background

### M17. Operator-console navigation and view architecture cleanup

- Build a proper app shell with a clear navigation model instead of one mixed monitoring page.
- Split the UI into distinct views:
  - Chat
  - Workflow Runs
  - Tasks / DAG
  - Agents
  - Artifacts
  - Observability / Events
  - Blueprint / Config
- Rebuild chat as the primary human-facing mode with a dedicated thread area, dedicated composer, clearer role styling, and contextual manager/approval behavior.
- Keep monitoring as separate inspection views with cleaner progressive disclosure and less noisy formatting.
- Verification result:
  - a new user can immediately locate where to chat and where to inspect run state
  - workflow runs are expandable/collapsible in a dedicated view rather than dumped beside chat
  - tasks, artifacts, agents, and events each render in clear dedicated sections
  - UI regression tests cover the new shell/navigation labels and updated empty/loading/error states

### M18. Operator-console loading and layout cleanup

- Remove the hard-coded 4-second UI snapshot timeout so the operator console no longer degrades into a false warning banner while canonical state is still loading.
- Keep first paint immediate by returning a loading shell while the snapshot refresh continues in the background.
- Give the sidebar its own scroll behavior so section navigation remains usable on smaller laptop-height screens.
- Simplify the Tasks / DAG view into vertical collapsible state groups rather than a wide multi-column layout that pushes content across the page.
- Verification result:
  - first-load UI state remains responsive while live snapshot refresh is in flight
  - the sidebar scrolls independently and cleanly
  - task-state inspection no longer overflows into a wide cross-page grid
  - monitoring regressions cover background refresh semantics and the clean-sqlite shortcut contract

## Workstreams and ownership

### Lead agent

- Owns shared contracts, planning files, package skeleton, integration, final verification, and drift tracking.
- Owns durable-pass gap analysis, milestone integration, native runtime validation, packaged-install validation, and documentation closeout.
- Owns integration of the monitoring command surface if it needs to be wired into a top-level CLI later.

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

- Owns `apps/cli/`, packaged project-template assets, and environment/bootstrap docs.
- Responsible for terminal entrypoints, template-based fresh-project scaffolding, `.env.example`, runtime docs, and packaged fresh-install validation assets.

### Monitoring UI workstream

- Owns `autoweave/monitoring/`.
- Responsible for the local run-inspection UI, workflow launch form, canonical read-only run summaries, promptable monitoring command surface, and workflow/agent visibility improvements.

### Final hardening workstream

- Owns the cross-cutting polish layer across `autoweave/local_runtime.py`, `autoweave/monitoring/`, `autoweave/compiler/`, `autoweave/workers/`, `autoweave/storage/`, and end-to-end tests.
- Responsible for resumable operator flow, runtime policy enforcement, lease/idempotency use, degraded-mode UX, and final repo-root plus packaged validation.

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

### M11

- config-loader tests for Gemini 3 profile definitions and default-selection behavior
- routing tests that verify the active default model can move to Gemini 3 without breaking Vertex normalization
- worker-path tests that verify OpenHands requests carry the selected Gemini 3 model string correctly
- live comparison steps for direct provider smoke tests, OpenHands runs, and repo-root example flow with Gemini 2.5 fallback preserved

### M12

- tests for task-input propagation into the worker prompt
- tests for explicit clarification marker handling and non-looping `needs_input` state transitions
- CLI/runtime tests for generic workflow-run behavior over multiple ready tasks
- packaged fresh-install validation with a custom project layout and live user brief
- completed outcome:
  - installed CLI can now run `autoweave run-workflow --request ...` in a fresh project
  - canonical task input is passed into the worker prompt and clarification markers map to authoritative AutoWeave human-loop state
  - fresh-project manager/backend/frontend/tester agent definitions and custom workflow were exercised against the live Docker stack
  - live packaged demo advanced the DAG durably, but vague briefs still did not consistently trigger a human clarification request from the real model

### M13

- tests for template-based bootstrap and validation rather than repo-root sample-only behavior
- tests for the monitoring UI launch flow and read-only run-inspection pages
- tests for current-run summaries, task/attempt/artifact rendering, and blocker visibility
- tests that the monitoring UI can accept a user request and start a workflow through the installed command surface

### M14

- workflow-instantiation fix so canonical `root_input_json` reaches every task, not only the entrypoint
- runtime dispatch preparation that merges workflow request, task-local input, and orchestrator-scoped upstream artifact summaries before worker launch
- OpenHands finish-event normalization so finish-tool action/observation payloads finalize canonical attempts/tasks as success
- success-path fallback artifact publication when a worker finishes with a usable summary but no explicit final domain artifact event
- live validation against the Dockerized OpenHands/Vertex stack proving:
  - manager plan completion
  - downstream parallel dispatch with preserved request context
  - real boutique storefront frontend output
  - canonical artifact publication for manager/frontend/backend contract tasks

### M15

- monitoring projection fix that separates canonical workflow status from live execution status
- operator-facing task execution projection for approval-gated, human-gated, dependency-waiting, and truly active worker states
- UI updates so run summaries show `no active worker` when execution is paused instead of implying a task is still running
- run ordering fix so the most relevant active run is surfaced before older blocked history once snapshot data is available
- regression coverage for execution-status payloads and blocked/paused run presentation

### M16

- add canonical repository support for deleting a workflow run and all subordinate records so stale local demo history can be purged safely
- add local cleanup tooling/CLI for stale demo runs and ignored runtime residue
- fix `new-project` so it no longer copies live secret material into a fresh project by default
- restore repo instruction files to repository guidance only and remove leaked run-specific memory
- rerun CLI, packaging, and test coverage after cleanup to ensure the repository still behaves as a library-first codebase
- completed implementation:
  - repository deletion support now exists for in-memory, SQLite, and Postgres-backed canonical stores
  - `cleanup-local-state` now purges canonical runs plus local generated residue
  - fresh-project scaffolding now requires an explicit user copy of the Vertex JSON instead of silently copying secrets
  - local runtime bootstrap no longer seeds `team_1.0_run` into canonical storage for read-only usage such as the monitor or doctor paths
  - repo-level instruction and root clutter cleanup were applied to the live workspace
- validation outcome:
  - targeted cleanup/storage tests passed
  - full `pytest -q` passed
  - `compileall` passed
  - live repo cleanup succeeded against the canonical backend
  - full live backend fixture validation remains partially gated by current sandbox DNS failures for the configured Neon and Neo4j Aura hosts

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
- The Gemini 3 migration pass is now complete: local/dev defaults are Gemini 3-first on `global`, with Gemini 2.5 preserved as fallback.
- The next pass should focus on broader live-run quality such as richer workspace seeding, quota-aware model fallback, and clearer rate-limit diagnostics under preview-model capacity pressure.
