"""Tiny local monitoring web app for AutoWeave workflow inspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from autoweave.monitoring.service import MonitoringService


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


class MonitoringDashboardApp:
    """Small WSGI app for launching and inspecting local AutoWeave workflows."""

    def __init__(self, service: MonitoringService) -> None:
        self.service = service

    def __call__(self, environ: Mapping[str, Any], start_response: Any) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if method == "GET" and path == "/":
            return self._respond(start_response, "200 OK", _render_index().encode("utf-8"), "text/html; charset=utf-8")
        if method == "GET" and path == "/api/state":
            query = parse_qs(str(environ.get("QUERY_STRING", "")))
            limit = max(1, int(query.get("limit", ["5"])[0]))
            payload = self.service.snapshot(limit=limit)
            return self._respond(start_response, "200 OK", _json_bytes(payload), "application/json")
        if method == "POST" and path == "/api/run":
            body = self._read_json_body(environ)
            request = str(body.get("request", "")).strip()
            if not request:
                return self._respond(
                    start_response,
                    "400 Bad Request",
                    _json_bytes({"error": "request is required"}),
                    "application/json",
                )
            max_steps = max(1, int(body.get("max_steps", 8)))
            dispatch = bool(body.get("dispatch", True))
            payload = self.service.launch_workflow(request=request, dispatch=dispatch, max_steps=max_steps)
            return self._respond(start_response, "202 Accepted", _json_bytes(payload), "application/json")
        return self._respond(
            start_response,
            "404 Not Found",
            _json_bytes({"error": f"unknown route {method} {path}"}),
            "application/json",
        )

    def _read_json_body(self, environ: Mapping[str, Any]) -> dict[str, Any]:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
        stream = environ.get("wsgi.input")
        if stream is None or content_length <= 0:
            return {}
        raw = stream.read(content_length)
        if not raw:
            return {}
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise TypeError("request body must be a JSON object")
        return loaded

    def _respond(self, start_response: Any, status: str, body: bytes, content_type: str) -> list[bytes]:
        start_response(
            status,
            [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [body]


def serve_dashboard(
    *,
    root: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    environ: Mapping[str, str] | None = None,
) -> None:
    service = MonitoringService(root=root, environ=environ)
    app = MonitoringDashboardApp(service)
    with make_server(host, port, app) as server:
        server.serve_forever()


def _render_index() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AutoWeave Monitor</title>
  <style>
    :root {
      --bg: #f3efe5;
      --panel: #fffaf1;
      --panel-2: #f8f2e6;
      --text: #1f1a15;
      --muted: #6b6158;
      --border: #d6c7b2;
      --accent: #8b5e34;
      --accent-2: #1e6f5c;
      --danger: #a12828;
      --mono: "SFMono-Regular", "Menlo", "Consolas", monospace;
      --sans: "Iowan Old Style", "Palatino", "Georgia", serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      background:
        radial-gradient(circle at top left, rgba(139,94,52,0.12), transparent 32%),
        radial-gradient(circle at bottom right, rgba(30,111,92,0.10), transparent 28%),
        var(--bg);
      color: var(--text);
      font-family: var(--sans);
    }
    h1, h2, h3 { margin: 0 0 12px; }
    h1 { font-size: 2rem; }
    p, li, label, button, input, textarea { font-size: 0.98rem; }
    .grid {
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 18px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(31,26,21,0.06);
    }
    .stack { display: grid; gap: 18px; }
    .muted { color: var(--muted); }
    textarea, input {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: white;
      color: var(--text);
      font-family: inherit;
    }
    textarea { min-height: 140px; resize: vertical; }
    button {
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      color: white;
      background: linear-gradient(135deg, var(--accent), #b0763e);
      cursor: pointer;
      font-weight: 700;
    }
    button:hover { filter: brightness(1.03); }
    .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .run-card {
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      background: var(--panel-2);
      margin-top: 12px;
    }
    .card-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    .mini-card {
      background: white;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px 12px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 0.92rem;
    }
    th, td {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    code, pre {
      font-family: var(--mono);
      font-size: 0.86rem;
    }
    pre {
      white-space: pre-wrap;
      background: white;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      overflow: auto;
    }
    details {
      margin-top: 10px;
      background: white;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 8px 10px;
    }
    summary {
      cursor: pointer;
      font-weight: 700;
    }
    .pill {
      display: inline-block;
      padding: 3px 9px;
      border-radius: 999px;
      background: rgba(139,94,52,0.12);
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 700;
      margin-right: 6px;
      margin-bottom: 6px;
    }
    .danger { color: var(--danger); }
    .ok { color: var(--accent-2); }
    @media (max-width: 980px) {
      body { padding: 14px; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="grid">
    <div class="stack">
      <section class="panel">
        <h1>AutoWeave Monitor</h1>
        <p class="muted">Launch a workflow from a user brief and inspect the canonical DAG, attempts, artifacts, blockers, and recent events.</p>
      </section>
      <section class="panel">
        <h2>Launch Workflow</h2>
        <form id="run-form">
          <label for="request">Prompt the manager entrypoint</label>
          <textarea id="request" name="request" placeholder="Build a clothing storefront for a boutique brand with Stripe checkout."></textarea>
          <p class="muted">This seeds the configured workflow entrypoint. The manager records the plan, and AutoWeave advances the canonical DAG while each worker attempt runs in its own sandbox.</p>
          <div class="row" style="margin-top:12px;">
            <label for="max_steps">Max steps</label>
            <input id="max_steps" name="max_steps" type="number" value="6" min="1" style="max-width:120px;">
            <label><input id="dispatch" name="dispatch" type="checkbox" checked> Dispatch to OpenHands</label>
          </div>
          <div class="row" style="margin-top:14px;">
            <button type="submit">Run</button>
            <span id="launch-status" class="muted"></span>
          </div>
        </form>
      </section>
      <section class="panel">
        <h2>Team</h2>
        <div id="agents" class="muted">Loading…</div>
      </section>
      <section class="panel">
        <h2>Workflow Blueprint</h2>
        <div id="blueprint" class="muted">Loading…</div>
      </section>
      <section class="panel">
        <h2>Launch Jobs</h2>
        <div id="jobs" class="muted">Loading…</div>
      </section>
    </div>
    <div class="stack">
      <section class="panel">
        <div class="row" style="justify-content:space-between;">
          <h2>Runs</h2>
          <span id="project-root" class="muted"></span>
        </div>
        <div id="runs" class="muted">Loading…</div>
      </section>
    </div>
  </div>
  <script>
    const launchStatus = document.getElementById("launch-status");
    const runsNode = document.getElementById("runs");
    const jobsNode = document.getElementById("jobs");
    const agentsNode = document.getElementById("agents");
    const blueprintNode = document.getElementById("blueprint");
    const projectRootNode = document.getElementById("project-root");

    function escapeHtml(text) {
      return String(text ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    function renderBlueprint(blueprint) {
      const pills = (blueprint.roles || []).map((role) => `<span class="pill">${escapeHtml(role)}</span>`).join("");
      const rows = (blueprint.templates || []).map((item) => `
        <tr>
          <td><code>${escapeHtml(item.key)}</code></td>
          <td>${escapeHtml(item.assigned_role)}</td>
          <td>${escapeHtml((item.hard_dependencies || []).join(", ") || "none")}</td>
          <td>${escapeHtml((item.produced_artifacts || []).join(", ") || "none")}</td>
        </tr>
      `).join("");
      blueprintNode.innerHTML = `
        <p><strong>${escapeHtml(blueprint.name)} ${escapeHtml(blueprint.version)}</strong> entrypoint <code>${escapeHtml(blueprint.entrypoint)}</code></p>
        <div>${pills}</div>
        <table>
          <thead><tr><th>Task</th><th>Role</th><th>Hard deps</th><th>Artifacts</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    function renderAgents(agents) {
      if (!agents.length) {
        agentsNode.innerHTML = '<p class="muted">No agent definitions found under the current project root.</p>';
        return;
      }
      agentsNode.innerHTML = `
        <div class="card-grid">
          ${agents.map((agent) => `
            <div class="mini-card">
              <div class="row" style="justify-content:space-between;">
                <strong>${escapeHtml(agent.role)}</strong>
                <span class="pill">${escapeHtml((agent.model_profile_hints || []).join(", ") || "default")}</span>
              </div>
              <div class="muted" style="margin-top:6px;">${escapeHtml(agent.specialization || "general")}</div>
              <p style="margin:10px 0 8px;">${escapeHtml(agent.description || agent.soul_excerpt || "")}</p>
              <div class="muted">Skills: ${escapeHtml((agent.skill_files || []).join(", ") || "none")}</div>
              <div class="muted">Tools: ${escapeHtml((agent.allowed_tool_groups || []).join(", ") || "none")}</div>
            </div>
          `).join("")}
        </div>
      `;
    }

    function renderJobs(jobs) {
      if (!jobs.length) {
        jobsNode.innerHTML = '<p class="muted">No UI-launched jobs yet.</p>';
        return;
      }
      jobsNode.innerHTML = jobs.map((job) => `
        <div class="run-card">
          <div class="row" style="justify-content:space-between;">
            <strong>${escapeHtml(job.status)}</strong>
            <code>${escapeHtml(job.id)}</code>
          </div>
          <p>${escapeHtml(job.request)}</p>
          ${job.workflow_run_id ? `<p class="muted">workflow_run_id <code>${escapeHtml(job.workflow_run_id)}</code></p>` : ""}
          ${job.error ? `<p class="danger">${escapeHtml(job.error)}</p>` : ""}
          ${job.summary_lines ? `<pre>${escapeHtml(job.summary_lines.join("\\n"))}</pre>` : ""}
          ${job.step_reports ? `
            <div class="card-grid">
              ${job.step_reports.map((step) => `
                <div class="mini-card">
                  <strong>${escapeHtml(step.task_key)}</strong><br>
                  <span class="muted">${escapeHtml(step.task_state)} / ${escapeHtml(step.attempt_state)}</span><br>
                  <span class="muted">${escapeHtml(step.route_model_name || "n/a")}</span>
                  ${step.failure_reason ? `<div class="danger" style="margin-top:6px;">${escapeHtml(step.failure_reason)}</div>` : ""}
                </div>
              `).join("")}
            </div>
          ` : ""}
        </div>
      `).join("");
    }

    function renderJsonBlock(value) {
      if (value === null || value === undefined || value === "") {
        return '<span class="muted">none</span>';
      }
      if (typeof value === "string") {
        return `<pre>${escapeHtml(value)}</pre>`;
      }
      return `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
    }

    function renderRuns(runs) {
      if (!runs.length) {
        runsNode.innerHTML = '<p class="muted">No persisted workflow runs found yet.</p>';
        return;
      }
      runsNode.innerHTML = runs.map((run) => {
        const stepCards = (run.run_steps || []).map((step) => `
          <div class="mini-card">
            <div class="row" style="justify-content:space-between;">
              <strong>#${escapeHtml(String(step.index))} ${escapeHtml(step.task_key)}</strong>
              <span class="pill">${escapeHtml(step.state)}</span>
            </div>
            <div class="muted">${escapeHtml(step.role)}${step.attempt_state ? ` · attempt ${escapeHtml(step.attempt_state)}` : ""}</div>
            ${step.block_reason ? `<div class="danger" style="margin-top:6px;">Blocked: ${escapeHtml(step.block_reason)}</div>` : ""}
            <details>
              <summary>Input</summary>
              ${renderJsonBlock(step.input_json)}
            </details>
            <details>
              <summary>Output</summary>
              ${renderJsonBlock(step.output_json)}
            </details>
            <div class="muted" style="margin-top:6px;">Artifacts: ${escapeHtml((step.produced_artifacts || []).join(", ") || "none")}</div>
          </div>
        `).join("");
        const taskRows = run.tasks.map((task) => `
          <tr>
            <td><code>${escapeHtml(task.task_key)}</code></td>
            <td>${escapeHtml(task.assigned_role)}</td>
            <td>${escapeHtml(task.state)}</td>
            <td>${escapeHtml(task.latest_attempt_state || "none")}</td>
            <td>${escapeHtml(task.block_reason || "none")}</td>
            <td><code>${escapeHtml(task.workspace_path || task.workspace_id || "n/a")}</code></td>
          </tr>
        `).join("");
        const attemptRows = run.attempts.map((attempt) => `
          <tr>
            <td><code>${escapeHtml(attempt.task_key || attempt.task_id)}</code></td>
            <td>${escapeHtml(String(attempt.attempt_number))}</td>
            <td>${escapeHtml(attempt.state)}</td>
            <td>${escapeHtml(attempt.model_name || "n/a")}</td>
            <td><code>${escapeHtml(attempt.workspace_path || attempt.workspace_id || "n/a")}</code></td>
          </tr>
        `).join("");
        const artifactRows = run.artifacts.map((artifact) => `
          <tr>
            <td><code>${escapeHtml(artifact.task_key || artifact.task_id)}</code></td>
            <td>${escapeHtml(artifact.artifact_type)}</td>
            <td>${escapeHtml(artifact.status)}</td>
            <td>${escapeHtml(artifact.title)}</td>
            <td>${escapeHtml(artifact.summary)}</td>
          </tr>
        `).join("");
        const humanRows = run.human_requests.map((request) => `
          <li><code>${escapeHtml(request.task_key || request.task_id)}</code>: ${escapeHtml(request.question)} (${escapeHtml(request.status)})</li>
        `).join("");
        const approvalRows = run.approval_requests.map((request) => `
          <li><code>${escapeHtml(request.task_key || request.task_id)}</code>: ${escapeHtml(request.reason)} (${escapeHtml(request.status)})</li>
        `).join("");
        const eventRows = run.events.map((event) => `
          <tr>
            <td>${escapeHtml(String(event.sequence_no))}</td>
            <td>${escapeHtml(event.event_type)}</td>
            <td>${escapeHtml(event.source)}</td>
            <td>${escapeHtml(event.agent_role || "")}</td>
            <td>${escapeHtml(event.message || "")}</td>
          </tr>
        `).join("");
        return `
          <div class="run-card">
            <div class="row" style="justify-content:space-between;">
              <div>
                <strong>${escapeHtml(run.status)}</strong>
                <code>${escapeHtml(run.id)}</code>
              </div>
              <span class="muted">graph v${escapeHtml(String(run.graph_revision || 1))} · ${escapeHtml(run.started_at || "")}</span>
            </div>
            <div class="card-grid" style="margin-top:14px;">
              <div class="mini-card">
                <div class="muted">User request</div>
                <strong>${escapeHtml(run.workflow_request || "none")}</strong>
              </div>
              <div class="mini-card">
                <div class="muted">Latest manager plan</div>
                <strong>${escapeHtml((run.manager_plan || run.manager_summary || "none").split("\\n")[0])}</strong>
              </div>
              <div class="mini-card">
                <div class="muted">Open blockers</div>
                <strong>${escapeHtml(String((run.human_requests || []).filter((item) => item.status === "open").length))} human</strong>
                <div><strong>${escapeHtml(String((run.approval_requests || []).filter((item) => item.status === "requested").length))} approval</strong></div>
              </div>
              <div class="mini-card">
                <div class="muted">Artifacts</div>
                <strong>${escapeHtml(String((run.artifacts || []).length))}</strong>
              </div>
            </div>
            ${run.manager_plan ? `<h3 style="margin-top:14px;">Manager Plan</h3><pre>${escapeHtml(run.manager_plan)}</pre>` : ""}
            ${run.manager_summary ? `<h3 style="margin-top:14px;">Manager Summary</h3><pre>${escapeHtml(run.manager_summary)}</pre>` : ""}
            <h3 style="margin-top:14px;">Run Steps</h3>
            <div class="card-grid">${stepCards || '<p class="muted">No run steps recorded yet.</p>'}</div>
            <h3 style="margin-top:14px;">Task Assignments</h3>
            <table><thead><tr><th>Task</th><th>Role</th><th>State</th><th>Attempt</th><th>Blocker</th><th>Workspace</th></tr></thead><tbody>${taskRows}</tbody></table>
            <h3 style="margin-top:14px;">Attempts</h3>
            <table><thead><tr><th>Task</th><th>#</th><th>State</th><th>Model</th><th>Workspace</th></tr></thead><tbody>${attemptRows}</tbody></table>
            <h3 style="margin-top:14px;">Artifacts</h3>
            <table><thead><tr><th>Task</th><th>Type</th><th>Status</th><th>Title</th><th>Summary</th></tr></thead><tbody>${artifactRows}</tbody></table>
            <h3 style="margin-top:14px;">Human Blockers</h3>
            ${humanRows ? `<ul>${humanRows}</ul>` : `<p class="ok">No open human requests.</p>`}
            <h3 style="margin-top:14px;">Approvals</h3>
            ${approvalRows ? `<ul>${approvalRows}</ul>` : `<p class="ok">No approval blockers.</p>`}
            <h3 style="margin-top:14px;">Recent Events</h3>
            <table><thead><tr><th>#</th><th>Type</th><th>Source</th><th>Role</th><th>Message</th></tr></thead><tbody>${eventRows}</tbody></table>
          </div>
        `;
      }).join("");
    }

    async function loadState() {
      const response = await fetch('/api/state');
      const state = await response.json();
      projectRootNode.textContent = state.project_root;
      renderAgents(state.agents || []);
      renderBlueprint(state.workflow_blueprint);
      renderJobs(state.jobs || []);
      renderRuns(state.runs || []);
    }

    document.getElementById('run-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      launchStatus.textContent = 'Launching...';
      const payload = {
        request: document.getElementById('request').value,
        max_steps: Number(document.getElementById('max_steps').value || '6'),
        dispatch: document.getElementById('dispatch').checked,
      };
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      launchStatus.textContent = response.ok ? `Started ${data.id}` : (data.error || 'launch failed');
      await loadState();
    });

    loadState();
    setInterval(loadState, 2000);
  </script>
</body>
</html>
"""
