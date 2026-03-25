"""Simple operator console for local AutoWeave workflow inspection."""

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
        if method == "POST" and path == "/api/chat":
            body = self._read_json_body(environ)
            message = str(body.get("message", "")).strip()
            if not message:
                return self._respond(
                    start_response,
                    "400 Bad Request",
                    _json_bytes({"error": "message is required"}),
                    "application/json",
                )
            workflow_run_id = str(body.get("workflow_run_id", "")).strip() or None
            human_request_id = str(body.get("human_request_id", "")).strip() or None
            max_steps = max(1, int(body.get("max_steps", 8)))
            dispatch = bool(body.get("dispatch", True))
            if workflow_run_id is not None and human_request_id is not None:
                payload = self.service.answer_human_request(
                    workflow_run_id=workflow_run_id,
                    request_id=human_request_id,
                    answer_text=message,
                    dispatch=dispatch,
                    max_steps=max_steps,
                )
            else:
                payload = self.service.launch_workflow(request=message, dispatch=dispatch, max_steps=max_steps)
            return self._respond(start_response, "202 Accepted", _json_bytes(payload), "application/json")
        if method == "POST" and path == "/api/approval":
            body = self._read_json_body(environ)
            workflow_run_id = str(body.get("workflow_run_id", "")).strip()
            approval_request_id = str(body.get("approval_request_id", "")).strip()
            if not workflow_run_id or not approval_request_id:
                return self._respond(
                    start_response,
                    "400 Bad Request",
                    _json_bytes({"error": "workflow_run_id and approval_request_id are required"}),
                    "application/json",
                )
            max_steps = max(1, int(body.get("max_steps", 8)))
            dispatch = bool(body.get("dispatch", True))
            approved = bool(body.get("approved", True))
            payload = self.service.resolve_approval_request(
                workflow_run_id=workflow_run_id,
                request_id=approval_request_id,
                approved=approved,
                dispatch=dispatch,
                max_steps=max_steps,
            )
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
  <title>AutoWeave Operator Console</title>
  <style>
    :root {
      --bg: #f5f1e8;
      --sidebar: #1d2824;
      --sidebar-panel: rgba(255,255,255,0.06);
      --panel: #fffdfa;
      --panel-soft: #f8f2e8;
      --text: #231c15;
      --muted: #6d6257;
      --line: #d9cfbf;
      --accent: #7b5635;
      --live: #2f5d88;
      --ok: #2d6e59;
      --warn: #9d6200;
      --bad: #a53d35;
      --shadow: 0 18px 40px rgba(35, 28, 21, 0.08);
      --radius: 18px;
      --sans: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
      --mono: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #f8f4ec 0%, #f3eee4 100%);
      color: var(--text);
      font-family: var(--sans);
      overflow-x: hidden;
    }
    h1, h2, h3, h4, p { margin: 0; }
    button, input, textarea, select { font: inherit; }
    button { border: 0; }
    pre {
      margin: 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      overflow: auto;
      max-width: 100%;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: var(--mono);
      font-size: 0.84rem;
    }
    .mono {
      font-family: var(--mono);
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .muted { color: var(--muted); }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
    }
    .sidebar {
      background: var(--sidebar);
      color: #f7f2ea;
      padding: 24px 18px;
      display: grid;
      grid-template-rows: auto auto 1fr;
      gap: 18px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
      overscroll-behavior: contain;
      scrollbar-gutter: stable;
    }
    .brand {
      display: grid;
      gap: 10px;
    }
    .brand h1 {
      font-size: 1.35rem;
      line-height: 1.1;
      letter-spacing: -0.03em;
    }
    .sidebar-card {
      background: var(--sidebar-panel);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px;
      padding: 14px;
      display: grid;
      gap: 10px;
    }
    .nav {
      display: grid;
      gap: 8px;
      align-content: start;
      min-height: 0;
      overflow-y: auto;
      padding-right: 4px;
    }
    .nav-button {
      width: 100%;
      text-align: left;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 12px;
      border-radius: 14px;
      cursor: pointer;
      color: inherit;
      background: transparent;
      border: 1px solid transparent;
    }
    .nav-button:hover {
      background: rgba(255,255,255,0.05);
      border-color: rgba(255,255,255,0.08);
    }
    .nav-button.active {
      background: rgba(255,255,255,0.12);
      border-color: rgba(255,255,255,0.12);
    }
    .nav-label {
      display: grid;
      gap: 2px;
    }
    .nav-label strong { font-size: 0.95rem; }
    .nav-label span {
      font-size: 0.78rem;
      color: rgba(247, 242, 234, 0.72);
    }
    .count {
      min-width: 30px;
      padding: 4px 8px;
      border-radius: 999px;
      text-align: center;
      background: rgba(255,255,255,0.12);
      font-size: 0.76rem;
      font-weight: 700;
    }
    .main {
      padding: 22px;
      display: grid;
      gap: 18px;
      min-width: 0;
      overflow-x: hidden;
    }
    .header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      flex-wrap: wrap;
    }
    .header-copy {
      display: grid;
      gap: 8px;
      max-width: 760px;
    }
    .header-copy h2 {
      font-size: 1.85rem;
      line-height: 1.05;
      letter-spacing: -0.03em;
    }
    .header-controls {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
      max-width: 100%;
    }
    .field {
      display: grid;
      gap: 6px;
      min-width: 0;
    }
    .select,
    .field input[type="number"],
    textarea {
      width: 100%;
      padding: 11px 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      color: var(--text);
    }
    textarea {
      min-height: 120px;
      resize: vertical;
    }
    .field input[type="number"] { width: 96px; }
    .btn {
      appearance: none;
      padding: 10px 16px;
      border-radius: 999px;
      font-weight: 700;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
    }
    .btn.secondary { background: var(--live); }
    .btn.subtle {
      background: rgba(123, 86, 53, 0.08);
      color: var(--text);
      border: 1px solid rgba(123, 86, 53, 0.12);
    }
    .btn.reject { background: var(--bad); }
    .pill-row,
    .row,
    .chip-row,
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 700;
      background: rgba(123, 86, 53, 0.10);
      color: var(--accent);
    }
    .pill.ok { background: rgba(45, 110, 89, 0.11); color: var(--ok); }
    .pill.live { background: rgba(47, 93, 136, 0.11); color: var(--live); }
    .pill.warn { background: rgba(157, 98, 0, 0.11); color: var(--warn); }
    .pill.bad { background: rgba(165, 61, 53, 0.11); color: var(--bad); }
    .sidebar .pill {
      background: rgba(255,255,255,0.12);
      color: #f7f2ea;
    }
    .banner {
      display: none;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid transparent;
      white-space: pre-wrap;
    }
    .banner.active { display: block; }
    .banner.info {
      background: rgba(47, 93, 136, 0.09);
      color: var(--live);
      border-color: rgba(47, 93, 136, 0.16);
    }
    .banner.warn {
      background: rgba(157, 98, 0, 0.09);
      color: var(--warn);
      border-color: rgba(157, 98, 0, 0.16);
    }
    .banner.error {
      background: rgba(165, 61, 53, 0.09);
      color: var(--bad);
      border-color: rgba(165, 61, 53, 0.16);
    }
    .surface {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 18px;
      min-width: 0;
    }
    .stack {
      display: grid;
      gap: 14px;
      min-width: 0;
    }
    .empty {
      padding: 22px 18px;
      border: 1px dashed var(--line);
      border-radius: 16px;
      background: var(--panel-soft);
      color: var(--muted);
    }
    .section {
      display: none;
      gap: 16px;
    }
    .section.active { display: grid; }
    .run-summary {
      display: grid;
      gap: 12px;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
    }
    .fact {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel-soft);
      padding: 12px;
      display: grid;
      gap: 4px;
      min-width: 0;
    }
    .chat-thread {
      display: grid;
      gap: 12px;
      min-height: 320px;
      max-height: 60vh;
      overflow: auto;
      padding-right: 4px;
    }
    .message {
      max-width: 88%;
      display: grid;
      gap: 8px;
      padding: 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: #fff;
      box-shadow: 0 8px 18px rgba(35, 28, 21, 0.04);
      overflow-wrap: anywhere;
    }
    .message.user {
      margin-left: auto;
      background: #fdf2e8;
    }
    .message.manager {
      background: #f5f8fd;
    }
    .message.system {
      background: #fffaf2;
      max-width: 100%;
    }
    .message-meta {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 0.82rem;
    }
    .run-groups,
    .card-grid,
    .event-list,
    .artifact-groups,
    .task-groups {
      display: grid;
      gap: 12px;
    }
    .task-groups {
      grid-template-columns: minmax(0, 1fr);
    }
    .run-group,
    .run-card,
    .card,
    .task-card,
    .event-card,
    .artifact-card {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fff;
      padding: 14px;
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .run-group > summary {
      list-style: none;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }
    .run-group > summary::-webkit-details-marker { display: none; }
    .run-group-body {
      margin-top: 12px;
      display: grid;
      gap: 12px;
    }
    .card-grid {
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    }
    .task-groups {
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    }
    .event-list {
      position: relative;
    }
    .event-list::before {
      content: "";
      position: absolute;
      left: 9px;
      top: 4px;
      bottom: 4px;
      width: 2px;
      background: rgba(123, 86, 53, 0.16);
    }
    .event-card {
      margin-left: 20px;
      position: relative;
    }
    .event-card::before {
      content: "";
      position: absolute;
      left: -18px;
      top: 16px;
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--accent);
    }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      .sidebar {
        position: static;
        height: auto;
      }
      .nav { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    }
    @media (max-width: 720px) {
      .main { padding: 14px; }
      .header { flex-direction: column; }
      .message { max-width: 100%; }
      .nav { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="pill-row">
          <span class="pill" id="global-status">loading</span>
          <span class="pill live" id="refresh-pill">idle</span>
        </div>
        <div>
          <h1>AutoWeave Operator Console</h1>
          <p style="margin-top:8px; color: rgba(247, 242, 234, 0.72); line-height: 1.45;">A simple manager chat and workflow inspection console for testing the library locally.</p>
        </div>
      </div>

      <div class="sidebar-card">
        <div class="muted" style="color: rgba(247, 242, 234, 0.72);">Project root</div>
        <div id="project-root" class="mono">Loading...</div>
        <div id="sidebar-run-status" class="pill-row"></div>
      </div>

      <nav class="nav" id="nav"></nav>
    </aside>

    <main class="main">
      <header class="header">
        <div class="header-copy">
          <div class="pill-row" id="header-pills"></div>
          <div>
            <h2 id="view-title">Chat</h2>
            <p id="view-subtitle" class="muted" style="margin-top:8px;">Talk to the manager-facing layer and inspect the system one section at a time.</p>
          </div>
          <div id="banner" class="banner"></div>
        </div>
        <div class="header-controls">
          <label class="field">
            <span class="muted">Selected run</span>
            <select id="run-select" class="select" style="width: min(100%, 320px);">
              <option value="">No runs available</option>
            </select>
          </label>
          <button id="refresh-btn" class="btn subtle" type="button">Refresh</button>
        </div>
      </header>

      <section id="section-chat" class="section active"></section>
      <section id="section-runs" class="section"></section>
      <section id="section-tasks" class="section"></section>
      <section id="section-agents" class="section"></section>
      <section id="section-artifacts" class="section"></section>
      <section id="section-events" class="section"></section>
      <section id="section-config" class="section"></section>
    </main>
  </div>

  <script>
    const VIEW_META = {
      chat: { label: "Chat", detail: "Manager conversation", title: "Chat", subtitle: "Talk to the manager-facing layer and answer clarifications or approvals here." },
      runs: { label: "Workflow Runs", detail: "Grouped run list", title: "Workflow Runs", subtitle: "Browse runs in clean groups and open the one you want to inspect." },
      tasks: { label: "Tasks / DAG", detail: "Task state and dependencies", title: "Tasks / DAG", subtitle: "Inspect task state, dependencies, attempts, and sandboxes for the selected run." },
      agents: { label: "Agents", detail: "Role definitions", title: "Agents", subtitle: "Review the packaged agent definitions, skill files, and approval policies." },
      artifacts: { label: "Artifacts", detail: "Published outputs", title: "Artifacts", subtitle: "Inspect artifacts grouped by the task that produced them." },
      events: { label: "Observability / Events", detail: "Recent telemetry", title: "Observability / Events", subtitle: "Read the recent event timeline separately from the manager chat." },
      config: { label: "Settings / Config", detail: "Workflow blueprint", title: "Settings / Config", subtitle: "Inspect the active workflow blueprint, entrypoint, roles, and dependencies." },
    };

    const state = {
      payload: null,
      selectedRunId: null,
      activeSection: normalizeSection(window.location.hash.replace(/^#/, "")),
      lastUpdatedAt: null,
    };

    const nodes = {
      globalStatus: document.getElementById("global-status"),
      refreshPill: document.getElementById("refresh-pill"),
      projectRoot: document.getElementById("project-root"),
      sidebarRunStatus: document.getElementById("sidebar-run-status"),
      nav: document.getElementById("nav"),
      headerPills: document.getElementById("header-pills"),
      viewTitle: document.getElementById("view-title"),
      viewSubtitle: document.getElementById("view-subtitle"),
      banner: document.getElementById("banner"),
      runSelect: document.getElementById("run-select"),
      refreshBtn: document.getElementById("refresh-btn"),
      sectionChat: document.getElementById("section-chat"),
      sectionRuns: document.getElementById("section-runs"),
      sectionTasks: document.getElementById("section-tasks"),
      sectionAgents: document.getElementById("section-agents"),
      sectionArtifacts: document.getElementById("section-artifacts"),
      sectionEvents: document.getElementById("section-events"),
      sectionConfig: document.getElementById("section-config"),
    };

    function normalizeSection(value) {
      return Object.prototype.hasOwnProperty.call(VIEW_META, value) ? value : "chat";
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function humanize(value) {
      return String(value || "unknown")
        .replace(/_/g, " ")
        .replace(/\\b\\w/g, (match) => match.toUpperCase());
    }

    function statusClass(status) {
      const normalized = String(status || "").toLowerCase();
      if (["ok", "completed", "approved", "resolved", "succeeded"].includes(normalized)) return "ok";
      if (["running", "queued", "ready", "loading", "refreshing", "active"].includes(normalized)) return "live";
      if (["waiting_for_dependency", "waiting_for_human", "waiting_for_approval", "blocked", "requested", "orphaned", "approval_gate", "awaiting_human", "dependency_wait", "idle"].includes(normalized)) return "warn";
      if (["failed", "error", "rejected"].includes(normalized)) return "bad";
      return "";
    }

    function pill(label, status) {
      return `<span class="pill ${statusClass(status || label)}">${escapeHtml(label)}</span>`;
    }

    function infoEmpty(message) {
      return `<div class="empty">${escapeHtml(message)}</div>`;
    }

    function selectedRun() {
      const runs = state.payload?.runs || [];
      if (!runs.length) return null;
      return runs.find((run) => run.id === state.selectedRunId) || runs[0];
    }

    function openHumanRequest(run) {
      return (run?.human_requests || []).find((item) => item.status === "open") || null;
    }

    function openApprovals(run) {
      return (run?.approval_requests || []).filter((item) => item.status === "requested");
    }

    function truncate(value, maxLength = 120) {
      const text = String(value || "");
      return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
    }

    function formatTime(value) {
      if (!value) return "n/a";
      const parsed = new Date(value);
      if (Number.isNaN(parsed.valueOf())) return String(value);
      return parsed.toLocaleString();
    }

    function lastUpdatedText() {
      if (!state.lastUpdatedAt) return "idle";
      return `updated ${state.lastUpdatedAt.toLocaleTimeString()}`;
    }

    function setActiveSection(section) {
      state.activeSection = normalizeSection(section);
      window.location.hash = state.activeSection;
      render();
    }

    function setSelectedRun(runId) {
      state.selectedRunId = runId || null;
      render();
    }

    function renderNav() {
      const payload = state.payload || {};
      const run = selectedRun();
      const counts = {
        chat: openHumanRequest(run) ? 1 : openApprovals(run).length,
        runs: (payload.runs || []).length,
        tasks: (run?.tasks || []).length,
        agents: (payload.agents || []).length,
        artifacts: (run?.artifacts || []).length,
        events: (run?.events || []).length,
        config: ((payload.workflow_blueprint || {}).templates || []).length,
      };
      nodes.nav.innerHTML = Object.entries(VIEW_META).map(([key, meta]) => `
        <button type="button" class="nav-button ${state.activeSection === key ? "active" : ""}" data-section="${escapeHtml(key)}">
          <span class="nav-label">
            <strong>${escapeHtml(meta.label)}</strong>
            <span>${escapeHtml(meta.detail)}</span>
          </span>
          <span class="count">${escapeHtml(counts[key])}</span>
        </button>
      `).join("");
      nodes.nav.querySelectorAll("[data-section]").forEach((button) => {
        button.addEventListener("click", () => setActiveSection(button.dataset.section || "chat"));
      });
    }

    function renderChrome() {
      const payload = state.payload || {};
      const run = selectedRun();
      const meta = VIEW_META[state.activeSection];
      nodes.globalStatus.textContent = payload.status || "loading";
      nodes.globalStatus.className = `pill ${statusClass(payload.status || "loading")}`;
      nodes.refreshPill.textContent = payload.refreshing ? "refreshing" : lastUpdatedText();
      nodes.refreshPill.className = `pill ${payload.refreshing ? "live" : ""}`;
      nodes.projectRoot.textContent = payload.project_root || "Loading...";
      nodes.viewTitle.textContent = meta.title;
      nodes.viewSubtitle.textContent = meta.subtitle;
      nodes.headerPills.innerHTML = [
        pill(payload.status || "loading", payload.status || "loading"),
        run ? pill(run.operator_status || run.status, run.operator_status || run.status) : pill("no run selected", "warn"),
        run ? pill(run.execution_status || "idle", run.execution_status || "idle") : "",
        run ? pill(`${(run.tasks || []).length} tasks`, "ok") : "",
        run ? pill(`${(run.artifacts || []).length} artifacts`, "ok") : "",
      ].filter(Boolean).join("");
      nodes.sidebarRunStatus.innerHTML = run
        ? [
            pill(run.operator_status || run.status, run.operator_status || run.status),
            pill(run.execution_status || "idle", run.execution_status || "idle"),
            pill(truncate(run.title || run.workflow_request || run.id, 28), "live"),
          ].join("")
        : pill("no run selected", "warn");

      const runs = payload.runs || [];
      nodes.runSelect.innerHTML = ['<option value="">No run selected</option>', ...runs.map((runItem) => `
        <option value="${escapeHtml(runItem.id)}" ${runItem.id === state.selectedRunId ? "selected" : ""}>
          ${escapeHtml(truncate(runItem.title || runItem.workflow_request || runItem.id, 68))}
        </option>
      `)].join("");

      const bannerLines = [];
      let bannerMode = "info";
      if (payload.load_error) {
        bannerLines.push(payload.load_error);
        bannerMode = payload.status === "degraded" ? "warn" : "error";
      }
      if (payload.refreshing && !bannerLines.length) {
        bannerLines.push("Refreshing live workflow state in the background.");
        bannerMode = "info";
      }
      nodes.banner.textContent = bannerLines.join("\\n");
      nodes.banner.className = bannerLines.length ? `banner active ${bannerMode}` : "banner";
    }

    function renderRunSummary(run) {
      if (!run) {
        return infoEmpty("No run selected. Start in Chat or pick a run in Workflow Runs.");
      }
      const openApprovals = (run.approval_requests || []).filter((item) => item.status === "requested").length;
      const openHumans = (run.human_requests || []).filter((item) => item.status === "open").length;
      const executionBannerClass = statusClass(run.execution_status || "idle") === "bad"
        ? "error"
        : statusClass(run.execution_status || "idle") === "live"
          ? "info"
          : "warn";
      return `
        <div class="surface run-summary">
          <div>
            <div class="pill-row">
              ${pill(run.operator_status || run.status, run.operator_status || run.status)}
              ${pill(run.execution_status || "idle", run.execution_status || "idle")}
              ${pill(`graph r${run.graph_revision}`, "ok")}
              ${pill(`${(run.attempts || []).length} attempts`, "ok")}
            </div>
            <h3 style="margin-top:10px;">${escapeHtml(run.title || run.workflow_request || run.id)}</h3>
            <p class="muted" style="margin-top:8px;">${escapeHtml(run.workflow_request || "No request recorded on this run.")}</p>
          </div>
          ${run.execution_summary ? `<div class="banner active ${executionBannerClass}">${escapeHtml(run.execution_summary)}</div>` : ""}
          <div class="summary-grid">
            <div class="fact"><span class="muted">Canonical workflow</span><strong>${escapeHtml(humanize(run.status))}</strong></div>
            <div class="fact"><span class="muted">Execution</span><strong>${escapeHtml(humanize(run.execution_status || "idle"))}</strong></div>
            <div class="fact"><span class="muted">Active workers</span><strong>${escapeHtml(run.active_attempt_count || 0)}</strong></div>
            <div class="fact"><span class="muted">Open approvals</span><strong>${escapeHtml(openApprovals)}</strong></div>
            <div class="fact"><span class="muted">Open human requests</span><strong>${escapeHtml(openHumans)}</strong></div>
            <div class="fact"><span class="muted">Started</span><strong>${escapeHtml(formatTime(run.started_at))}</strong></div>
            <div class="fact"><span class="muted">Artifacts</span><strong>${escapeHtml((run.artifacts || []).length)}</strong></div>
          </div>
          ${run.manager_summary ? `<pre>${escapeHtml(run.manager_summary)}</pre>` : ""}
        </div>
      `;
    }

    function renderChatSection() {
      const run = selectedRun();
      const openHuman = openHumanRequest(run);
      const approvals = openApprovals(run);
      const messages = run?.chat_messages || [];
      const composerLabel = openHuman ? "Reply to manager question" : "Prompt the manager";
      const composerHint = openHuman
        ? "Your reply will answer the selected run's open human request."
        : approvals.length
          ? "Execution is paused. No worker is running until you resolve the approval below."
          : "Send a new request to the manager. The orchestrator remains the source of truth for the runnable DAG.";

      nodes.sectionChat.innerHTML = `
        ${renderRunSummary(run)}
        <div class="surface stack">
          <div>
            <h3>Manager chat</h3>
            <p class="muted" style="margin-top:8px;">The primary human-facing surface for prompts, clarifications, approvals, and execution notes.</p>
          </div>
          <div class="chat-thread" id="chat-thread">
            ${run ? renderMessages(messages, run) : infoEmpty("No run selected yet. Start with a manager prompt to create one.")}
          </div>
        </div>
        <div class="surface stack">
          <div>
            <h3>${escapeHtml(composerLabel)}</h3>
            <p class="muted" style="margin-top:8px;">${escapeHtml(composerHint)}</p>
          </div>
          <label class="field">
            <span class="sr-only">Manager chat input</span>
            <textarea id="composer-message" placeholder="Build a small clothing ecommerce storefront. Ask me if pricing, shipping, or checkout details are missing."></textarea>
          </label>
          <div class="row" style="justify-content:space-between; align-items:flex-end;">
            <div class="row">
              <label class="field">
                <span class="muted">Max steps</span>
                <input id="composer-max-steps" type="number" min="1" value="6">
              </label>
              <label class="row muted">
                <input id="composer-dispatch" type="checkbox" checked>
                Dispatch to OpenHands
              </label>
            </div>
            <button id="composer-send" class="btn" type="button">${openHuman ? "Send answer" : "Start run"}</button>
          </div>
          <div id="composer-status" class="muted"></div>
        </div>
      `;

      const composerMessage = document.getElementById("composer-message");
      const composerMaxSteps = document.getElementById("composer-max-steps");
      const composerDispatch = document.getElementById("composer-dispatch");
      const composerStatus = document.getElementById("composer-status");
      document.getElementById("composer-send")?.addEventListener("click", async () => {
        const message = composerMessage.value.trim();
        if (!message) {
          composerStatus.textContent = "Enter a message first.";
          return;
        }
        composerStatus.textContent = openHuman ? "Sending answer..." : "Launching run...";
        try {
          if (run && openHuman) {
            await postJson("/api/chat", {
              message,
              workflow_run_id: run.id,
              human_request_id: openHuman.id,
              dispatch: composerDispatch.checked,
              max_steps: Number(composerMaxSteps.value || "6"),
            });
          } else {
            await postJson("/api/chat", {
              message,
              dispatch: composerDispatch.checked,
              max_steps: Number(composerMaxSteps.value || "6"),
            });
          }
          composerMessage.value = "";
          composerStatus.textContent = "Queued.";
          await loadState();
        } catch (error) {
          composerStatus.textContent = String(error);
        }
      });

      nodes.sectionChat.querySelectorAll("[data-approval-action]").forEach((button) => {
        button.addEventListener("click", async () => {
          const approved = button.dataset.approvalAction === "approve";
          const workflowRunId = button.dataset.workflowRunId || "";
          const approvalRequestId = button.dataset.approvalRequestId || "";
          composerStatus.textContent = approved ? "Approving..." : "Rejecting...";
          try {
            await postJson("/api/approval", {
              workflow_run_id: workflowRunId,
              approval_request_id: approvalRequestId,
              approved,
              dispatch: composerDispatch.checked,
              max_steps: Number(composerMaxSteps.value || "6"),
            });
            composerStatus.textContent = approved ? "Approval queued." : "Rejection queued.";
            await loadState();
          } catch (error) {
            composerStatus.textContent = String(error);
          }
        });
      });
    }

    function renderMessages(messages, run) {
      if (!messages.length) {
        return infoEmpty("No chat messages yet. Manager plans, clarifications, approvals, and operator replies will appear here.");
      }
      return messages.map((message) => {
        const actions = message.kind === "approval_request" && message.status === "requested" ? `
          <div class="actions">
            <button type="button" class="btn secondary" data-approval-action="approve" data-workflow-run-id="${escapeHtml(run.id)}" data-approval-request-id="${escapeHtml(message.id)}">Approve</button>
            <button type="button" class="btn reject" data-approval-action="reject" data-workflow-run-id="${escapeHtml(run.id)}" data-approval-request-id="${escapeHtml(message.id)}">Reject</button>
          </div>
        ` : "";
        return `
          <article class="message ${escapeHtml(message.role || "system")}">
            <div class="message-meta">
              <div class="pill-row">
                ${pill(humanize(message.role || "system"), message.role || "")}
                ${pill(humanize(message.kind || "message"), message.kind || "")}
                ${message.status ? pill(humanize(message.status), message.status) : ""}
              </div>
              <span class="mono">${escapeHtml(truncate(run.id, 24))}</span>
            </div>
            <div>${escapeHtml(message.text || "")}</div>
            ${actions}
          </article>
        `;
      }).join("");
    }

    function renderRunsSection() {
      const runs = state.payload?.runs || [];
      if (!runs.length) {
        nodes.sectionRuns.innerHTML = `<div class="surface">${infoEmpty("No workflow runs yet. Use Chat to start one.")}</div>`;
        return;
      }
      const groups = {
        active: runs.filter((run) => ["active", "ready"].includes(run.execution_status)),
        attention: runs.filter((run) => ["blocked", "waiting_for_human", "waiting_for_approval", "idle"].includes(run.execution_status) || ["blocked", "waiting_for_human", "waiting_for_approval"].includes(run.operator_status)),
        complete: runs.filter((run) => run.execution_status === "completed" || run.operator_status === "completed"),
        failed: runs.filter((run) => run.execution_status === "failed" || run.operator_status === "failed"),
      };
      const groupMeta = [
        ["active", "Active", "Runs with a live worker or immediate dispatchable work."],
        ["attention", "Needs attention", "Runs paused on approvals, human input, or a hard block."],
        ["complete", "Completed", "Runs that finished successfully."],
        ["failed", "Failed", "Runs that ended in a failed terminal state."],
      ];
      nodes.sectionRuns.innerHTML = `
        <div class="surface stack">
          <div>
            <h3>Workflow Runs</h3>
            <p class="muted" style="margin-top:8px;">Runs are grouped and collapsed so the page stays readable even when history grows.</p>
          </div>
          <div class="run-groups">
            ${groupMeta.map(([key, title, description]) => `
              <details class="run-group" ${key === "active" || key === "attention" ? "open" : ""}>
                <summary>
                  <div>
                    <strong>${escapeHtml(title)}</strong>
                    <div class="muted" style="margin-top:4px;">${escapeHtml(description)}</div>
                  </div>
                  <span class="count">${escapeHtml(groups[key].length)}</span>
                </summary>
                <div class="run-group-body">
                  ${groups[key].length ? groups[key].map((run) => `
                    <article class="run-card">
                      <div class="row" style="justify-content:space-between; align-items:flex-start;">
                        <div>
                          <strong>${escapeHtml(run.title || run.workflow_request || run.id)}</strong>
                          <div class="mono muted" style="margin-top:6px;">${escapeHtml(run.id)}</div>
                        </div>
                        <div class="pill-row">
                          ${pill(run.operator_status || run.status, run.operator_status || run.status)}
                          ${pill(run.execution_status || "idle", run.execution_status || "idle")}
                          ${pill(`${(run.tasks || []).length} tasks`, "ok")}
                        </div>
                      </div>
                      <p class="muted">${escapeHtml(truncate(run.execution_summary || run.operator_summary || run.workflow_request || "No summary available.", 160))}</p>
                      <div class="actions">
                        <button type="button" class="btn subtle" data-run-select="${escapeHtml(run.id)}">Select</button>
                        <button type="button" class="btn secondary" data-open-section="chat" data-run-id="${escapeHtml(run.id)}">Open chat</button>
                        <button type="button" class="btn subtle" data-open-section="tasks" data-run-id="${escapeHtml(run.id)}">Open tasks</button>
                      </div>
                    </article>
                  `).join("") : infoEmpty("No runs in this group.")}
                </div>
              </details>
            `).join("")}
          </div>
        </div>
      `;
      nodes.sectionRuns.querySelectorAll("[data-run-select]").forEach((button) => {
        button.addEventListener("click", () => setSelectedRun(button.dataset.runSelect || ""));
      });
      nodes.sectionRuns.querySelectorAll("[data-open-section]").forEach((button) => {
        button.addEventListener("click", () => {
          setSelectedRun(button.dataset.runId || "");
          setActiveSection(button.dataset.openSection || "chat");
        });
      });
    }

    function renderTasksSection() {
      const run = selectedRun();
      if (!run) {
        nodes.sectionTasks.innerHTML = `<div class="surface">${infoEmpty("Select a run to inspect tasks and dependencies.")}</div>`;
        return;
      }
      const groups = [
        ["Active workers", run.tasks.filter((task) => task.has_active_worker)],
        ["Ready to dispatch", run.tasks.filter((task) => task.state === "ready")],
        ["Waiting on people or policy", run.tasks.filter((task) => ["waiting_for_human", "waiting_for_approval"].includes(task.state))],
        ["Waiting on dependencies", run.tasks.filter((task) => task.state === "waiting_for_dependency")],
        ["Blocked", run.tasks.filter((task) => task.state === "blocked")],
        ["Completed", run.tasks.filter((task) => task.state === "completed")],
        ["Failed", run.tasks.filter((task) => task.state === "failed")],
      ];
      nodes.sectionTasks.innerHTML = `
        ${renderRunSummary(run)}
        <div class="surface stack">
          <div>
            <h3>Tasks / DAG</h3>
            <p class="muted" style="margin-top:8px;">Each group shows one execution state so blocked branches do not visually swamp healthy or completed work.</p>
          </div>
          <div class="task-groups">
            ${groups.map(([label, tasks]) => `
              <details class="run-group task-group" ${tasks.length && !["Completed", "Failed"].includes(label) ? "open" : ""}>
                <summary>
                  <div>
                    <strong>${escapeHtml(label)}</strong>
                    <div class="muted" style="margin-top:4px;">${tasks.length ? `${tasks.length} task(s) currently in this state.` : "No tasks currently in this state."}</div>
                  </div>
                  <span class="count">${escapeHtml(tasks.length)}</span>
                </summary>
                <div class="run-group-body">
                  ${tasks.length ? tasks.map((task) => `
                    <article class="task-card">
                      <div class="row" style="justify-content:space-between; align-items:flex-start;">
                        <div>
                          <strong>${escapeHtml(task.title || task.task_key)}</strong>
                          <div class="muted" style="margin-top:4px;">${escapeHtml(task.task_key)} • ${escapeHtml(task.assigned_role || "unassigned")}</div>
                        </div>
                        <div class="pill-row">
                          ${pill(task.state, task.state)}
                          ${task.attempt_display_state ? pill(task.attempt_display_state, task.attempt_display_state) : task.latest_attempt_state ? pill(task.latest_attempt_state, task.latest_attempt_state) : ""}
                        </div>
                      </div>
                      ${task.description ? `<p>${escapeHtml(task.description)}</p>` : ""}
                      ${task.block_reason ? `<div class="banner active warn">${escapeHtml(task.block_reason)}</div>` : ""}
                      ${task.worker_summary ? `<div class="banner active ${statusClass(task.worker_status || task.state) === "live" ? "info" : statusClass(task.worker_status || task.state) === "bad" ? "error" : "warn"}">${escapeHtml(task.worker_summary)}</div>` : ""}
                      <div class="chip-row">
                        ${(task.hard_dependencies || []).length ? task.hard_dependencies.map((dep) => `<span class="pill">${escapeHtml(dep)}</span>`).join("") : `<span class="pill">no hard deps</span>`}
                      </div>
                      <div class="chip-row">
                        ${(task.required_artifact_types || []).length ? task.required_artifact_types.map((artifactType) => `<span class="pill">${escapeHtml(artifactType)}</span>`).join("") : `<span class="pill">no required artifacts</span>`}
                        ${(task.produced_artifact_types || []).length ? task.produced_artifact_types.map((artifactType) => `<span class="pill ok">${escapeHtml(artifactType)}</span>`).join("") : ""}
                      </div>
                      ${task.workspace_path ? `<pre>${escapeHtml(task.workspace_path)}</pre>` : ""}
                    </article>
                  `).join("") : infoEmpty("No tasks in this state group.")}
                </div>
              </details>
            `).join("")}
          </div>
        </div>
      `;
    }

    function renderAgentsSection() {
      const agents = state.payload?.agents || [];
      nodes.sectionAgents.innerHTML = `
        <div class="surface stack">
          <div>
            <h3>Agents</h3>
            <p class="muted" style="margin-top:8px;">Role definitions, packaged skills, and approval policies for the current project.</p>
          </div>
          <div class="card-grid">
            ${agents.length ? agents.map((agent) => `
              <article class="card">
                <div class="row" style="justify-content:space-between; align-items:flex-start;">
                  <div>
                    <strong>${escapeHtml(agent.name || agent.role)}</strong>
                    <div class="muted" style="margin-top:4px;">${escapeHtml(agent.role)}</div>
                  </div>
                  ${pill(agent.approval_policy || "default", agent.approval_policy || "")}
                </div>
                <p>${escapeHtml(agent.description || agent.specialization || "No description available.")}</p>
                <div class="chip-row">
                  ${(agent.primary_skills || []).map((skill) => `<span class="pill">${escapeHtml(skill)}</span>`).join("") || `<span class="pill">no primary skill labels</span>`}
                </div>
                <div class="chip-row">
                  ${(agent.allowed_workflow_stages || []).map((stage) => `<span class="pill live">${escapeHtml(stage)}</span>`).join("") || `<span class="pill">all workflow stages</span>`}
                </div>
                ${agent.skill_files?.length ? `<p class="muted">Skill files: ${escapeHtml(agent.skill_files.join(", "))}</p>` : ""}
              </article>
            `).join("") : infoEmpty("No agents found under ./agents.")}
          </div>
        </div>
      `;
    }

    function renderArtifactsSection() {
      const run = selectedRun();
      if (!run) {
        nodes.sectionArtifacts.innerHTML = `<div class="surface">${infoEmpty("Select a run to inspect artifacts.")}</div>`;
        return;
      }
      const grouped = {};
      for (const artifact of run.artifacts || []) {
        const key = artifact.task_key || "unassigned";
        grouped[key] = grouped[key] || [];
        grouped[key].push(artifact);
      }
      nodes.sectionArtifacts.innerHTML = `
        ${renderRunSummary(run)}
        <div class="surface stack">
          <div>
            <h3>Artifacts</h3>
            <p class="muted" style="margin-top:8px;">Artifacts are grouped by producing task to make dependency flow easier to follow.</p>
          </div>
          <div class="artifact-groups">
            ${Object.keys(grouped).length ? Object.entries(grouped).map(([taskKey, artifacts]) => `
              <div class="card stack">
                <div class="row" style="justify-content:space-between;">
                  <strong>${escapeHtml(taskKey)}</strong>
                  ${pill(`${artifacts.length} artifact(s)`, "ok")}
                </div>
                ${artifacts.map((artifact) => `
                  <article class="artifact-card">
                    <div class="row" style="justify-content:space-between; align-items:flex-start;">
                      <div>
                        <strong>${escapeHtml(artifact.title || artifact.artifact_type)}</strong>
                        <div class="muted" style="margin-top:4px;">${escapeHtml(artifact.artifact_type)}</div>
                      </div>
                      ${pill(artifact.status, artifact.status)}
                    </div>
                    <p>${escapeHtml(artifact.summary || "No summary available.")}</p>
                    <pre>${escapeHtml(artifact.storage_uri || "No storage URI recorded.")}</pre>
                  </article>
                `).join("")}
              </div>
            `).join("") : infoEmpty("No artifacts published for this run.")}
          </div>
        </div>
      `;
    }

    function renderEventsSection() {
      const run = selectedRun();
      if (!run) {
        nodes.sectionEvents.innerHTML = `<div class="surface">${infoEmpty("Select a run to inspect recent events.")}</div>`;
        return;
      }
      nodes.sectionEvents.innerHTML = `
        ${renderRunSummary(run)}
        <div class="surface stack">
          <div>
            <h3>Observability / Events</h3>
            <p class="muted" style="margin-top:8px;">The event timeline is separate from chat so progress notes do not crowd the conversation.</p>
          </div>
          <div class="event-list">
            ${(run.events || []).length ? run.events.map((event) => `
              <article class="event-card">
                <div class="row" style="justify-content:space-between; align-items:flex-start;">
                  <div>
                    <strong>${escapeHtml(event.event_type || "event")}</strong>
                    <div class="muted" style="margin-top:4px;">${escapeHtml(event.source || "source")} • ${escapeHtml(event.agent_role || "system")}</div>
                  </div>
                  <div class="pill-row">
                    ${pill(`#${event.sequence_no}`, "ok")}
                    ${event.model_name ? pill(event.model_name, "live") : ""}
                  </div>
                </div>
                <p>${escapeHtml(event.message || "No event message captured.")}</p>
              </article>
            `).join("") : infoEmpty("No recent events for this run.")}
          </div>
        </div>
      `;
    }

    function renderConfigSection() {
      const blueprint = state.payload?.workflow_blueprint || {};
      const templates = blueprint.templates || [];
      nodes.sectionConfig.innerHTML = `
        <div class="surface stack">
          <div>
            <h3>Settings / Config</h3>
            <p class="muted" style="margin-top:8px;">This is the active packaged workflow blueprint used by the orchestrator.</p>
          </div>
          <div class="summary-grid">
            <div class="fact"><span class="muted">Workflow</span><strong>${escapeHtml(blueprint.name || "unknown")}</strong></div>
            <div class="fact"><span class="muted">Version</span><strong>${escapeHtml(blueprint.version || "n/a")}</strong></div>
            <div class="fact"><span class="muted">Entrypoint</span><strong>${escapeHtml(blueprint.entrypoint || "n/a")}</strong></div>
            <div class="fact"><span class="muted">Roles</span><strong>${escapeHtml((blueprint.roles || []).join(", ") || "n/a")}</strong></div>
          </div>
          <div class="card-grid">
            ${templates.length ? templates.map((template) => `
              <article class="card">
                <div class="row" style="justify-content:space-between; align-items:flex-start;">
                  <div>
                    <strong>${escapeHtml(template.title || template.key)}</strong>
                    <div class="muted" style="margin-top:4px;">${escapeHtml(template.key)} • ${escapeHtml(template.assigned_role || "unassigned")}</div>
                  </div>
                  ${(template.approval_requirements || []).length ? pill("approval gate", "warn") : ""}
                </div>
                ${template.description_template ? `<p>${escapeHtml(template.description_template)}</p>` : ""}
                <div class="chip-row">
                  ${(template.hard_dependencies || []).length ? template.hard_dependencies.map((dep) => `<span class="pill">${escapeHtml(dep)}</span>`).join("") : `<span class="pill">no hard deps</span>`}
                </div>
                <div class="chip-row">
                  ${(template.produced_artifacts || []).length ? template.produced_artifacts.map((artifactType) => `<span class="pill ok">${escapeHtml(artifactType)}</span>`).join("") : ""}
                  ${(template.required_artifacts || []).length ? template.required_artifacts.map((artifactType) => `<span class="pill">${escapeHtml(artifactType)}</span>`).join("") : ""}
                </div>
              </article>
            `).join("") : infoEmpty("No workflow blueprint templates loaded.")}
          </div>
        </div>
      `;
    }

    function render() {
      renderNav();
      renderChrome();
      document.querySelectorAll(".section").forEach((section) => section.classList.remove("active"));
      document.getElementById(`section-${state.activeSection}`)?.classList.add("active");
      renderChatSection();
      renderRunsSection();
      renderTasksSection();
      renderAgentsSection();
      renderArtifactsSection();
      renderEventsSection();
      renderConfigSection();
    }

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error || response.statusText);
      }
      return body;
    }

    async function loadState() {
      nodes.refreshPill.textContent = "refreshing";
      nodes.refreshPill.className = "pill live";
      try {
        const response = await fetch("/api/state?limit=8");
        if (!response.ok) {
          throw new Error(`state request failed: ${response.status}`);
        }
        state.payload = await response.json();
        const runs = state.payload.runs || [];
        if (!state.selectedRunId || !runs.some((run) => run.id === state.selectedRunId)) {
          state.selectedRunId = state.payload.selected_run_id || (runs[0] ? runs[0].id : null);
        }
        state.lastUpdatedAt = new Date();
        render();
      } catch (error) {
        nodes.banner.textContent = String(error);
        nodes.banner.className = "banner active error";
      }
    }

    nodes.runSelect.addEventListener("change", (event) => setSelectedRun(event.target.value));
    nodes.refreshBtn.addEventListener("click", () => loadState());
    window.addEventListener("hashchange", () => {
      state.activeSection = normalizeSection(window.location.hash.replace(/^#/, ""));
      render();
    });

    loadState();
    setInterval(loadState, 6000);
  </script>
</body>
</html>
"""
