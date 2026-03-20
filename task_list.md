# AutoWeave Task List

| Status | Owner | Task | Dependencies | Touched modules/files | Merge checkpoint |
| --- | --- | --- | --- | --- | --- |
| done | lead | Copy source-of-truth docs into `docs/` and verify presence | none | `docs/` | startup contract satisfied |
| done | lead | Read all three design docs in order and check for contradictions | docs present | `docs/` | architecture baseline accepted |
| done | lead | Create repository instruction and planning files | doc read complete | `AGENTS.md`, `context.md`, `implementation_plan.md`, `task_list.md`, `.env.example` | planning baseline created |
| done | lead | Scaffold Python package layout and shared core contracts | planning baseline | `autoweave/`, `apps/cli/`, `tests/`, `pyproject.toml` | shared interfaces frozen for subagents |
| done | lead | Define shared domain models, enums, and protocol boundaries | package layout | `autoweave/models.py`, `autoweave/types.py`, `autoweave/protocols.py` | contract freeze v1 |
| done | orchestration | Implement workflow schema loader and DAG parser | contract freeze v1 | `autoweave/workflows/` | parser merged |
| done | orchestration | Implement task and attempt state machines | contract freeze v1 | `autoweave/orchestration/` | state machine merged |
| done | orchestration | Implement scheduler, readiness evaluator, and graph revision handling | workflow parser, state machines | `autoweave/orchestration/`, `autoweave/workflows/` | orchestration slice integrated |
| done | orchestration | Implement human-loop orchestration and authoritative state transition rules | state machines | `autoweave/orchestration/`, `autoweave/approvals/` | orchestration checkpoint A |
| done | runtime | Implement canonical config loaders and validators | contract freeze v1 | `autoweave/compiler/`, `autoweave/config/` | config foundation merged |
| done | runtime | Implement model routing and route audit records | config loaders | `autoweave/routing/`, `autoweave/workers/` | routing checkpoint |
| done | runtime | Implement OpenHands config compiler and runtime env injection | routing, config loaders | `autoweave/compiler/`, `autoweave/workers/` | compiler checkpoint |
| done | runtime | Implement remote worker adapter and workspace lifecycle scaffolding | compiler checkpoint | `autoweave/workers/` | runtime checkpoint |
| done | storage_memory | Implement repository protocols and in-memory/test adapters for canonical entities | contract freeze v1 | `autoweave/storage/` | storage checkpoint A |
| done | storage_memory | Implement artifact registry and visibility resolver | storage checkpoint A | `autoweave/artifacts/` | artifact checkpoint |
| done | storage_memory | Implement context service and typed miss handling | storage checkpoint A | `autoweave/context/`, `autoweave/memory/` | context checkpoint |
| done | storage_memory | Implement Redis lease/idempotency abstractions and Celery job contracts | storage checkpoint A | `autoweave/storage/` | coordination checkpoint |
| done | storage_memory | Implement Neo4j projection contracts and graph query layer | storage checkpoint A | `autoweave/graph/` | graph checkpoint |
| done | observability_testing | Implement canonical event schema and event service | contract freeze v1 | `autoweave/events/` | event checkpoint |
| done | observability_testing | Implement tracing, metrics, replay metadata, and redaction helpers | event checkpoint | `autoweave/observability/` | observability checkpoint |
| done | observability_testing | Add deterministic unit/integration/e2e tests for required edge cases | all feature slices | `tests/` | test checkpoint |
| done | cli_dx | Implement terminal CLI entrypoints and config bootstrap | package layout | `apps/cli/` | CLI checkpoint |
| done | cli_dx | Add sample agents, workflow, and runtime config fixtures | config foundation | `agents/`, `configs/` | DX checkpoint |
| done | lead | Integrate all workstreams and reconcile contract mismatches | all checkpoints above | cross-cutting | integration checkpoint 1 |
| done | lead | Run full implemented test plan and record gaps | integration checkpoint 1 | `tests/`, `context.md`, `task_list.md` | verification checkpoint |
| done | lead | Fix Vertex IAM for live worker bootstrap | local/runtime validation complete | `.env.local`, Vertex IAM, OpenHands worker path | IAM boundary cleared |
| done | lead | Record milestone retrospective and prompt-vs-implementation drift notes | verification checkpoint | `context.md`, `task_list.md` | milestone closeout |
| done | lead | Re-read design docs and current planning files before repair pass | existing repo state | `docs/`, `context.md`, `implementation_plan.md`, `task_list.md` | repair audit baseline |
| done | lead | Record short gap analysis in `context.md` before major changes | repair audit baseline | `context.md` | gap report logged |
| done | lead | Normalize env loading and move Vertex credentials into `config/secrets/vertex_service_account.json` | gap report logged | `.env.example`, `.env.local`, `config/secrets/`, runtime wiring | env checkpoint |
| done | infra | Add Docker/Docker Compose for local Redis, OpenHands Agent Server, and artifact storage | env checkpoint | `docker-compose.yml`, infra scripts/docs | infra checkpoint |
| done | runtime | Add central runtime settings/bootstrap for Neon, Neo4j, Redis, artifact store, Vertex, and OpenHands | env checkpoint | `autoweave/settings.py`, `autoweave/local_runtime.py`, `apps/cli/` | bootstrap checkpoint |
| done | storage_memory | Add service-backed connection/config wiring while preserving canonical contracts | runtime bootstrap | `autoweave/storage/`, `autoweave/artifacts/`, `autoweave/context/`, `autoweave/graph/` | storage wiring checkpoint |
| done | runtime | Add OpenHands agent-server client/bootstrap wiring and local worker integration contract | runtime bootstrap | `autoweave/workers/`, `autoweave/compiler/` | worker integration checkpoint |
| done | observability_testing | Expand tests for env resolution, credential-path normalization, service wiring, and retry/recovery edges | env/runtime/storage changes | `tests/` | repair verification checkpoint |
| done | lead | Validate Docker Compose config, run repaired local test suite, and update planning files with final local run commands | all repair checkpoints | root docs and tests | repair closeout |
| done | lead | Re-read design docs plus `AGENTS.md`, `context.md`, `implementation_plan.md`, and `task_list.md` before the durable-runtime pass | repair closeout | `docs/`, `AGENTS.md`, `context.md`, `implementation_plan.md`, `task_list.md` | durable-pass audit baseline |
| done | lead | Record durable-runtime gap analysis before major changes | durable-pass audit baseline | `context.md` | durable gap report logged |
| done | lead | Update `AGENTS.md`, `implementation_plan.md`, and `task_list.md` for the durable-runtime pass | durable gap report logged | `AGENTS.md`, `implementation_plan.md`, `task_list.md` | durable plan checkpoint |
| done | storage_memory | Implement real Postgres-backed canonical repositories and schema/bootstrap helpers | durable plan checkpoint | `autoweave/storage/`, `autoweave/models.py`, `autoweave/protocols.py`, config/runtime wiring | storage milestone M7 |
| done | storage_memory | Implement Redis-backed lease, heartbeat, dispatch, and idempotency coordination | durable plan checkpoint | `autoweave/storage/`, runtime wiring, tests | coordination milestone M7 |
| done | storage_memory | Persist artifact metadata canonically while keeping payloads in local storage | Postgres repositories | `autoweave/artifacts/`, `autoweave/storage/`, tests | artifact milestone M7/M8 |
| done | storage_memory | Implement real Neo4j-backed projection/query adapter with non-authoritative semantics | Postgres repositories | `autoweave/graph/`, tests | graph milestone M7 |
| done | runtime | Replace transient local runtime state with a durable orchestration runtime composition | Postgres repositories, Redis coordination | `autoweave/local_runtime.py`, `autoweave/orchestration/`, `autoweave/storage/`, CLI wiring | runtime milestone M7 |
| done | runtime | Complete OpenHands dispatch, progress capture, artifact/result harvesting, and durable attempt finalization | durable runtime composition, artifact metadata persistence | `autoweave/workers/`, `autoweave/events/`, `autoweave/observability/`, `autoweave/orchestration/`, `autoweave/local_runtime.py` | worker lifecycle milestone M8 |
| done | infra | Add Dockerized AutoWeave runtime/app service with health checks, env loading, workspace/artifact volumes, and startup ordering | durable runtime composition | `docker-compose.yml`, `Dockerfile`, `.dockerignore`, `README.md` | infra milestone M9 |
| done | cli_dx | Update CLI/docs for local runtime commands, packaging, and fresh-project execution | infra milestone, runtime milestone | `README.md`, `.env.example` | DX milestone M9 |
| done | observability_testing | Expand tests for durable storage, Redis recovery, Neo4j projection isolation, OpenHands lifecycle, artifact harvesting, and retry/idempotency edges | storage and runtime milestones | `tests/test_storage_durable.py`, `tests/test_storage_service_wiring.py`, `tests/test_packaging.py` | durable verification checkpoint |
| done | lead | Run native repo end-to-end validation against the Dockerized local stack and fix failures until stable | Docker daemon access | runtime/infra/test artifacts | native validation checkpoint |
| done | lead | Build/package/install the library into clean environments and validate fresh-project demo flows | packaging setup, docs, demo workspace | `build_backend.py`, `tests/test_packaging.py`, `README.md`, packaged wheel installs under `/tmp` | package validation checkpoint |
| done | lead | Update `context.md` and `task_list.md` with final drift notes, remaining limitations, and exact run commands | package validation checkpoint | `context.md`, `task_list.md`, docs | durable pass closeout |
| done | lead | Re-read design docs plus `AGENTS.md`, `context.md`, `implementation_plan.md`, and `task_list.md` before the Vertex debugging pass | durable pass closeout | `docs/`, `AGENTS.md`, `context.md`, `implementation_plan.md`, `task_list.md` | Vertex debug audit baseline |
| done | lead | Record focused empty-response gap analysis and debugging plan before major changes | Vertex debug audit baseline | `context.md` | Vertex debug plan logged |
| done | runtime | Record exact OpenHands, LiteLLM, and Google/Vertex dependency versions in the live runtime path | Vertex debug plan logged | runtime container, diagnostics notes, `context.md` | version audit checkpoint |
| done | runtime | Record the exact AutoWeave -> OpenHands model/provider/tool/runtime payload used for the failing run | Vertex debug plan logged | `autoweave/compiler/`, `autoweave/workers/`, runtime diagnostics, replay artifacts | payload audit checkpoint |
| done | runtime | Build a direct LiteLLM -> Vertex reproduction for the same model/provider config and compare non-streaming vs streaming | version audit checkpoint | runtime diagnostics, repro scripts/tests, `context.md` | LiteLLM repro checkpoint |
| done | runtime | Isolate tools-disabled vs tools-enabled behavior for the Vertex/OpenHands path | LiteLLM repro checkpoint | `autoweave/workers/`, runtime diagnostics, replay artifacts | tool-path checkpoint |
| done | runtime | Patch the narrowest provider-specific fix and add fail-fast protection against repeated empty-response loops | payload audit checkpoint, LiteLLM repro checkpoint, tool-path checkpoint | `autoweave/workers/`, `autoweave/local_runtime.py`, runtime wiring | runtime stabilization checkpoint |
| done | runtime | Align strict runtime config schema with checked-in `configs/runtime/runtime.yaml` so live bootstrap no longer fails on `celery_queue_names` | runtime stabilization checkpoint | `autoweave/config_models.py`, `tests/test_runtime.py` | config bootstrap checkpoint |
| done | observability_testing | Add regression tests for Vertex provider/model normalization, empty-response handling, non-streaming fallback if needed, and non-looping failure behavior | runtime stabilization checkpoint | `tests/test_runtime.py`, `tests/test_local_runtime.py` | Vertex regression checkpoint |
| done | lead | Re-run direct Vertex/LiteLLM reproduction, OpenHands runtime path, and `run-example --dispatch`, then document exact root cause and working config | runtime stabilization checkpoint, Vertex regression checkpoint | runtime/test artifacts, `context.md`, docs | Vertex debug closeout |
| blocked | lead | Achieve a successful live Vertex-backed task completion through the repo-root example workflow | Vertex empty-response loop fixed; current live run now exits through timeout/finalization after Vertex rate-limit pressure and a still-minimal workspace context | OpenHands live runtime, Vertex quota/capacity, workspace seeding | external runtime-quality boundary |
