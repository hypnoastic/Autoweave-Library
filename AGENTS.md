Read `docs/autoweave_high_level_architecture.md`, `docs/autoweave_implementation_spec.md`, and `docs/autoweave_diagrams_source.md` before planning or coding.

Maintain `context.md`, `implementation_plan.md`, and `task_list.md` as live project-control files.

For large changes, use explicit multi-agent execution where safe. Prefer one isolated workstream per major module area. If git worktrees are unavailable, use subagents with disjoint file ownership and integrate through the lead agent.

Do not bypass the architecture docs. AutoWeave remains the sole orchestrator, OpenHands remains the worker runtime, Postgres remains canonical truth, and Neo4j stays a projection/query layer.

Stop at the credential boundary before live cloud-backed integration tests. Never hardcode or fake secrets.

For the current durable-runtime pass, keep Neon Postgres, Neo4j Aura, and Vertex AI external; run Redis, OpenHands Agent Server, local artifact storage, and the AutoWeave runtime locally through Docker.

Normalize Vertex credentials to `config/secrets/vertex_service_account.json` and keep both `VERTEXAI_SERVICE_ACCOUNT_FILE` and `GOOGLE_APPLICATION_CREDENTIALS` pointed there. Never commit secret material.

Before major coding, record a short repo-state gap analysis in `context.md`, then update `implementation_plan.md` and `task_list.md` with workstream ownership, acceptance criteria, and validation steps.

For the current Vertex worker-path debugging pass, establish the exact OpenHands, LiteLLM, and Vertex configuration first. Reproduce the failure directly outside OpenHands before patching the runtime path. Do not paper over repeated empty responses with retries alone; identify whether the fault is model/provider routing, LiteLLM versioning, streaming, tool-calling, or OpenHands loop handling and record the evidence in `context.md`.

Do not declare the pass complete until both validations succeed:
- native repo runtime validation against the local Docker stack
- packaged fresh-install validation in a clean environment

Update `context.md` and `task_list.md` after each milestone with status, decisions, gaps, and drift from the design docs or build prompt.

For the current library-separation and monitoring-UI pass, keep bundled sample project assets distinct from the library implementation by treating them as packaged templates or example projects, not as implicit library state. Any UI added in this pass must remain a lightweight local operator/debugging surface over canonical AutoWeave state; it must not bypass the orchestrator or become a separate workflow authority.
