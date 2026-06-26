# CLI Reference

The AutoWeave CLI is the primary way to interact with the orchestration engine locally. You can access it by running `autoweave` or `uv run autoweave`.

## Commands

- `autoweave status`: Show a minimal repository status summary.
- `autoweave validate`: Validate docs, configs, and sample agent fixtures.
- `autoweave bootstrap`: Create missing sample agents and config fixtures.
- `autoweave migrate-project`: Refresh packaged AutoWeave project-managed files to the latest library templates.
- `autoweave create-agent`: Create a new agent bundle with soul, playbook, config, and skills.
- `autoweave doctor`: Inspect local env, configs, and the OpenHands bootstrap path.
- `autoweave run-example`: Run the notifications example against the composed local runtime.
- `autoweave run-workflow`: Run the current workflow from a user request instead of the fixed sample brief.
- `autoweave worker`: Run a real Celery worker for queued AutoWeave workflow execution.
- `autoweave ui`: Launch the lightweight local monitoring UI.
- `autoweave start`: Start the entire local execution environment: UI and Celery worker.
- `autoweave cleanup-local-state`: Purge stale canonical runs and local generated runtime residue.
- `autoweave new-project`: Initialize a new AutoWeave project.
