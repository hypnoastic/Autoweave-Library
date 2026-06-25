"""HTML shell for the lightweight AutoWeave operator console and docs playground."""

from __future__ import annotations


def render_dashboard_page() -> str:
    return """<!DOCTYPE html>
<html class="dark" lang="en">
<head>
    <meta charset="utf-8"/>
    <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
    <title>AutoWeave Library | Documentation & Playground</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,container-queries,typography"></script>
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,100..800;1,100..800&amp;display=swap" rel="stylesheet"/>
    <link href="https://cdn.jsdelivr.net/gh/vernnont/geist-font@v1.0.1/geist.css" rel="stylesheet"/>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js"></script>
    
    <style>
        :root {
            --bg-base: #0a0a0a;
            --bg-panel: #111111;
            --bg-card: #161616;
            --border-subtle: #242424;
            --text-main: #ededed;
            --text-muted: #a1a1aa;
            --accent: #ededed;
        }

        body { 
            background-color: var(--bg-base); 
            color: var(--text-main); 
            font-family: 'Geist', sans-serif; 
            overflow: hidden; 
        }

        /* Markdown Styles */
        .markdown-body {
            color: var(--text-main);
            font-size: 15px;
            line-height: 1.6;
        }
        .markdown-body h1 { font-size: 2em; font-weight: 600; margin-bottom: 0.5em; letter-spacing: -0.02em; }
        .markdown-body h2 { font-size: 1.5em; font-weight: 600; margin-top: 1.5em; margin-bottom: 0.5em; border-bottom: 1px solid var(--border-subtle); padding-bottom: 0.3em; letter-spacing: -0.01em; }
        .markdown-body h3 { font-size: 1.25em; font-weight: 600; margin-top: 1.25em; margin-bottom: 0.5em; }
        .markdown-body p { margin-top: 0; margin-bottom: 1em; color: var(--text-muted); }
        .markdown-body a { color: var(--accent); text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 2px; }
        .markdown-body code { font-family: 'JetBrains Mono', monospace; font-size: 0.85em; background: rgba(255,255,255,0.1); padding: 0.2em 0.4em; border-radius: 3px; }
        .markdown-body pre { background: var(--bg-card); padding: 1em; border-radius: 6px; overflow-x: auto; border: 1px solid var(--border-subtle); margin-bottom: 1em; }
        .markdown-body pre code { background: transparent; padding: 0; color: #e2e8f0; }
        .markdown-body ul { margin-top: 0; margin-bottom: 1em; padding-left: 2em; color: var(--text-muted); list-style-type: disc; }
        .markdown-body li { margin-bottom: 0.25em; }

        .material-symbols-outlined { font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20; font-size: 18px; }
        .custom-scrollbar::-webkit-scrollbar { width: 4px; height: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #2A2A2A; border-radius: 2px; }
        
        .nav-item {
            transition: all 0.2s ease;
            color: var(--text-muted);
        }
        .nav-item:hover {
            color: var(--text-main);
            background: var(--bg-panel);
        }
        .nav-item.active {
            color: var(--text-main);
            background: var(--bg-card);
            border-left: 2px solid var(--accent);
            font-weight: 500;
        }

        .status-glow-executing { box-shadow: 0 0 8px rgba(255, 255, 255, 0.1); }
        .empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 2rem; opacity: 0.5; height: 100%; text-align: center; }

        [x-cloak] { display: none !important; }
    </style>
    <script id="tailwind-config">
        tailwind.config = {
          darkMode: "class",
          theme: {
            extend: {
              colors: {
                  base: "#0a0a0a",
                  panel: "#111111",
                  card: "#161616",
                  borderSubtle: "#242424",
                  textMain: "#ededed",
                  textMuted: "#a1a1aa",
              },
              fontFamily: {
                  sans: ["Geist", "sans-serif"],
                  mono: ["JetBrains Mono", "monospace"],
              }
            }
          }
        }
    </script>
</head>
<body class="flex h-screen w-screen bg-base text-textMain font-sans selection:bg-white/20">

<!-- SideNavBar -->
<aside class="w-64 border-r border-borderSubtle bg-base flex flex-col h-full overflow-y-auto hidden md:flex shrink-0">
    <div class="p-6 flex items-center gap-3">
        <div class="w-8 h-8 rounded bg-white text-black flex items-center justify-center">
            <span class="material-symbols-outlined font-bold" style="font-variation-settings: 'FILL' 1;">terminal</span>
        </div>
        <div>
            <h1 class="text-sm font-semibold tracking-tight">AutoWeave</h1>
            <p class="text-[11px] font-mono text-textMuted uppercase tracking-wider">Library &bull; v2.4.0</p>
        </div>
    </div>
    
    <nav class="mt-2 flex-1 px-3 space-y-1">
        <div class="px-3 text-xs font-semibold text-textMuted uppercase tracking-wider mb-2 mt-4">Getting Started</div>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('overview')" id="nav-overview">
            <span class="material-symbols-outlined">book</span>Overview
        </a>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('installation')" id="nav-installation">
            <span class="material-symbols-outlined">download</span>Installation
        </a>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('quickstart')" id="nav-quickstart">
            <span class="material-symbols-outlined">bolt</span>Quick Start
        </a>
        
        <div class="px-3 text-xs font-semibold text-textMuted uppercase tracking-wider mb-2 mt-6">Concepts</div>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('core-concepts')" id="nav-core-concepts">
            <span class="material-symbols-outlined">architecture</span>Core Concepts
        </a>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('usage-examples')" id="nav-usage-examples">
            <span class="material-symbols-outlined">code</span>Usage Examples
        </a>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('api-reference')" id="nav-api-reference">
            <span class="material-symbols-outlined">api</span>API Reference
        </a>
        
        <div class="px-3 text-xs font-semibold text-textMuted uppercase tracking-wider mb-2 mt-6">Interact</div>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('playground')" id="nav-playground">
            <span class="material-symbols-outlined">play_circle</span>Playground / Demo
        </a>
        
        <div class="px-3 text-xs font-semibold text-textMuted uppercase tracking-wider mb-2 mt-6">Quality</div>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('testing')" id="nav-testing">
            <span class="material-symbols-outlined">fact_check</span>Testing & Coverage
        </a>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('security')" id="nav-security">
            <span class="material-symbols-outlined">shield</span>Security
        </a>
        <a class="nav-item flex items-center gap-3 px-3 py-2 rounded-md text-sm cursor-pointer" onclick="navigate('cicd')" id="nav-cicd">
            <span class="material-symbols-outlined">rocket_launch</span>CI/CD
        </a>
    </nav>
    
    <div class="p-4 mt-auto border-t border-borderSubtle">
        <div class="flex items-center justify-between">
            <div class="flex flex-col">
                <span class="text-xs font-semibold text-textMain">Local Worker</span>
                <span class="text-[10px] font-mono text-textMuted flex items-center gap-1 mt-0.5" id="refresh-status">
                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Connecting...
                </span>
            </div>
            <a href="https://github.com" target="_blank" class="text-textMuted hover:text-textMain">
                <span class="material-symbols-outlined">code_blocks</span>
            </a>
        </div>
    </div>
</aside>

<!-- Main Area -->
<main class="flex-1 flex flex-col min-w-0 bg-base relative">

    <!-- Topbar Mobile (hidden on desktop) -->
    <header class="md:hidden w-full h-14 border-b border-borderSubtle bg-base flex items-center px-4 shrink-0">
        <button class="mr-4 text-textMain"><span class="material-symbols-outlined">menu</span></button>
        <span class="font-semibold">AutoWeave</span>
    </header>

    <!-- Content Container -->
    <div id="content-container" class="flex-1 overflow-y-auto custom-scrollbar relative">
        
        <!-- Markdown Pages -->
        <div id="page-content" class="max-w-4xl mx-auto px-6 lg:px-12 py-10 hidden w-full">
            <div id="markdown-container" class="markdown-body"></div>
        </div>

        <!-- Playground View -->
        <div id="playground-content" class="hidden h-full flex flex-col lg:flex-row w-full absolute inset-0">
            <!-- Left Pane: Manager Chat -->
            <section class="flex-1 flex flex-col border-r border-borderSubtle bg-base relative">
                <div class="p-4 border-b border-borderSubtle flex items-center justify-between shrink-0">
                    <div class="flex items-center gap-2">
                        <span class="material-symbols-outlined text-textMuted">forum</span>
                        <h2 class="text-sm font-semibold tracking-wide">Manager Chat</h2>
                    </div>
                    <div class="flex items-center gap-2 text-xs font-mono text-textMuted">
                        <span class="w-2 h-2 rounded-full bg-white animate-pulse"></span> LIVE FEED
                    </div>
                </div>
                
                <div id="chat-thread" class="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4 font-mono text-xs">
                    <!-- dynamic feed -->
                </div>
                
                <form id="chat-composer" class="p-4 bg-panel border-t border-borderSubtle shrink-0">
                    <div class="flex flex-col gap-2">
                        <div class="flex items-center gap-3 bg-base border border-borderSubtle rounded-md p-2 focus-within:border-textMuted transition-all shadow-sm">
                            <span class="font-mono text-textMuted ml-2">$</span>
                            <input id="composer-input" class="flex-1 bg-transparent border-none focus:ring-0 font-mono text-sm placeholder:text-textMuted/50 text-textMain outline-none" placeholder="Send command or request..." type="text"/>
                            <button id="composer-submit" type="submit" class="bg-white text-black p-1.5 rounded flex items-center justify-center hover:bg-gray-200 transition-colors">
                                <span class="material-symbols-outlined" style="font-variation-settings: 'FILL' 1;">send</span>
                            </button>
                        </div>
                        <div class="flex items-center justify-between px-2">
                            <label class="flex items-center gap-2 text-textMuted text-xs font-mono">
                                Mode:
                                <select id="composer-dispatch" class="bg-base border border-borderSubtle rounded px-2 py-1 text-textMain outline-none focus:border-textMuted cursor-pointer">
                                    <option value="true" selected>Live Execution</option>
                                    <option value="false">Dry Run</option>
                                </select>
                            </label>
                            <span id="composer-hint" class="text-xs text-textMuted font-mono"></span>
                        </div>
                    </div>
                </form>
            </section>

            <!-- Right Pane: Execution DAG -->
            <section class="w-full lg:w-[400px] flex flex-col bg-panel shrink-0">
                <div class="p-4 border-b border-borderSubtle bg-base shrink-0">
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex flex-col">
                            <span class="text-[10px] uppercase font-bold tracking-wider text-textMuted">Current Run</span>
                            <h3 class="text-lg font-bold font-mono truncate" id="run-summary-id">No Active Run</h3>
                        </div>
                        <div id="run-summary-status-pill" class="flex items-center gap-2 px-3 py-1 rounded-full border border-borderSubtle bg-panel">
                            <span id="run-summary-status-dot" class="w-1.5 h-1.5 rounded-full bg-textMuted"></span>
                            <span id="run-summary-status" class="text-xs font-mono text-textMuted uppercase">Idle</span>
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                        <div class="p-3 border border-borderSubtle rounded-md bg-base flex flex-col justify-center">
                            <span class="text-[10px] uppercase font-bold tracking-wider text-textMuted mb-1">Operator</span>
                            <span class="font-mono text-sm text-textMain" id="run-op-status">-</span>
                        </div>
                        <div class="p-3 border border-borderSubtle rounded-md bg-base flex flex-col justify-center">
                            <span class="text-[10px] uppercase font-bold tracking-wider text-textMuted mb-1">Active Workers</span>
                            <span class="font-mono text-sm text-textMain" id="run-workers">0</span>
                        </div>
                    </div>
                </div>

                <div class="flex-1 flex flex-col overflow-y-auto custom-scrollbar bg-base">
                    <div class="px-4 py-2 bg-panel border-b border-borderSubtle flex items-center justify-between sticky top-0 z-10">
                        <span class="text-[10px] uppercase font-bold tracking-wider text-textMuted">Execution DAG</span>
                        <span class="text-[10px] font-mono text-textMuted" id="task-count">0 tasks</span>
                    </div>
                    <div id="task-list" class="flex-1 flex flex-col"></div>
                </div>
            </section>
        </div>

    </div>
</main>

<script>
    // DOCS CONTENT STORE
    const docs = {
        'overview': `
# AutoWeave Library

AutoWeave is a terminal-first multi-agent orchestration library built around OpenHands remote workers and Vertex AI.

This package provides the runtime execution engine, durable workflow state management, Celery queue integration, human-in-the-loop coordination, and local monitoring primitives.

It is designed to be installed as a pure Python dependency by downstream products (like an AutoWeave Web layer), keeping execution semantics and durable state completely decoupled from product-facing surfaces.

### Core Capabilities
* **Workflow Orchestration**: Define, compile, and execute DAGs of agentic tasks.
* **Durable State**: Resume paused runs, track attempts, and persist context safely.
* **Human-in-the-Loop**: Native primitives for pausing execution to request approvals or clarifications.
* **Queue Dispatch**: Offload long-running tasks to Celery workers.
* **Local Monitoring**: Inspect local runs natively via this lightweight UI.

### Production Ready
AutoWeave library is designed with standard Python packaging, exhaustive typing, comprehensive automated testing, and secure CI/CD pipelines.
        `,
        'installation': `
# Installation

AutoWeave Library is published as a Python package.

### Prerequisites
* Python >= 3.10
* A local environment map (e.g. \`.env.local\`) containing your Vertex AI, Postgres, Redis, and Neo4j connection URIs if running the full persistent stack.

### Install via pip

\`\`\`bash
pip install autoweave
\`\`\`

### Install via uv (Recommended)

\`\`\`bash
uv pip install autoweave
\`\`\`

### For Local Development

Clone the repository and install it in editable mode with development dependencies:

\`\`\`bash
git clone https://github.com/autoweave/autoweave-library.git
cd autoweave-library
uv pip install -e ".[dev]"
\`\`\`
        `,
        'quickstart': `
# Quick Start

Here is a minimal example of booting the local runtime and executing a workflow.

### 1. Initialize a Project Root

AutoWeave requires a project directory to store local configurations.

\`\`\`bash
autoweave new-project ./my-weave-project
autoweave bootstrap --root ./my-weave-project
\`\`\`

### 2. Run a Simple Workflow

\`\`\`bash
autoweave run-workflow \\
    --root ./my-weave-project \\
    --request "Write a script that prints Hello World"
\`\`\`

### 3. Start the Monitoring UI

You can view the execution state, DAG, and manager chat locally:

\`\`\`bash
autoweave ui --root ./my-weave-project
\`\`\`

Navigate to \`http://localhost:8765\` to see this exact interface.
        `,
        'core-concepts': `
# Core Concepts

AutoWeave separates the **Product Shell** from the **Runtime Engine**. This library *is* the Runtime Engine.

### 1. Workflow Compiler
User requests are passed to the \`compiler\`. It takes a natural language request, grounds it in repository context (Neo4j/Vector DB), and emits an execution DAG of \`Tasks\`.

### 2. Execution DAG & Tasks
Workflows are modeled as a DAG. Each \`Task\` is routed to an assigned \`role\` (e.g., Code Writer, QA Reviewer).

### 3. Workers & Queues
If \`dispatch=True\` and \`--queue\` is used, tasks are serialized and sent to a **Celery Worker**. The worker deserializes the task, provisions an OpenHands remote runtime, and executes.

### 4. Human Approval Pauses
When an agent determines it needs human input, it emits an \`ApprovalRequest\`. The runtime pauses the task. The web layer (or local UI) captures this and prompts the user. Responding to the request resumes the execution DAG automatically.

### 5. Durable State
Every run, task, attempt, event, and artifact is persisted to Postgres/SQLite natively.
        `,
        'usage-examples': `
# Usage Examples

### Using the Python API

You do not have to use the CLI. Downstream backends will instantiate the runtime directly:

\`\`\`python
from autoweave.orchestration.runtime import build_local_runtime

# Initialize the runtime
runtime = build_local_runtime(root_path="./my-project")

# Launch a workflow programmaticly
workflow_run = runtime.launch_workflow(
    request="Review the backend contract and propose next steps"
)

print(f"Started run: {workflow_run.id}")
\`\`\`

### Resolving Approvals

\`\`\`python
from autoweave.approvals.service import resolve_approval_request

# Approved by a human from a web dashboard
resolve_approval_request(
    workflow_run_id="run_123",
    request_id="req_abc",
    approved=True,
    runtime=runtime
)
\`\`\`
        `,
        'api-reference': `
# API Reference

AutoWeave exposes a minimal public surface area for external Python consumption.

### \`build_local_runtime(root_path: Path) -> LocalRuntime\`
Constructs the full dependency-injected runtime engine. Requires a configured `.env.local` inside the `root_path`.

### \`bootstrap_project(root_path: Path) -> None\`
Scaffolds the necessary fixtures, local DB structure, and template files into a target directory.

### \`migrate_project(root_path: Path) -> None\`
Refreshes template-managed files to newer packaged defaults if the library version is updated.

### \`load_env_map(root_path: Path) -> dict\`
Loads and merges the local environment variables cleanly, respecting standard \`.env\` hierarchies.

### \`AttemptState\` / \`TaskState\`
Enums representing the durable lifecycle states of workflow nodes. Valid states include \`pending\`, \`running\`, \`paused\`, \`succeeded\`, \`failed\`.
        `,
        'testing': `
# Testing & Quality

AutoWeave is tested rigorously to ensure production-grade reliability of the orchestration engine. 

### Coverage Target
We enforce a strict **80%+ overall line coverage** threshold. Pull requests failing this constraint will block merging in CI.

### Test Matrix

1. **Unit Tests**: Validates compilation, template generation, and state machine transitions.
2. **Integration Tests**: Tests full orchestration loops via \`test_orchestration.py\` using mock worker executors.
3. **Queue/Celery Tests**: Validates \`test_celery_queue.py\` behavior.
4. **Storage Tests**: \`test_storage_durable.py\` verifies Postgres/SQLite persistence schemas.
5. **UI / Documentation Tests**: Headless browser tests (Playwright) ensure this local dashboard functions flawlessly.
6. **Package Smoke Tests**: Verifies \`pip install\` works from the compiled `.whl` and entrypoints execute without \`ImportError\`.

Run locally:
\`\`\`bash
pytest tests/ -v
\`\`\`
        `,
        'security': `
# Security

As a runtime engine executing agent-generated commands, security is paramount.

### Threat Model
* **Trusted Environments**: AutoWeave runs in trusted environments (developer laptops, backend clusters). 
* **Worker Isolation**: Remote workers (OpenHands) must run inside sandboxed environments (Docker/gVisor). AutoWeave orchestrates them but *does not* provide the sandbox itself.
* **Dependencies**: Automated dependency audits via \`pip-audit\`.

### Validations
* Input validation is strictly enforced via \`pydantic\` for all runtime state models.
* No unsafe \`eval()\` or \`exec()\` is used within the Python orchestration layer.
* CodeQL static analysis runs on every pull request.

### Local Credentials
AutoWeave uses `.env.local` for credentials. It explicitly \`.gitignore\`s these files during `bootstrap`.
        `,
        'cicd': `
# CI/CD

AutoWeave uses GitHub Actions for continuous integration and delivery.

### 1. \`ci.yml\` (Pull Requests & Main)
* **Linting**: \`ruff check\` and \`ruff format\`
* **Typechecking**: \`mypy\` strictly enforced
* **Tests**: \`pytest\` and \`pytest-cov\`
* **Build**: \`python -m build\`
* **Smoke Test**: Installs the `.whl` into an isolated virtualenv and tests \`autoweave --help\`.

### 2. \`security.yml\` (Pull Requests, Main, Schedule)
* **Pip Audit**: Scans dependencies for known vulnerabilities.
* **CodeQL**: Runs GitHub's static analyzer for Python vulnerabilities.
* **Secret Scanning**: Rejects commits containing hardcoded secrets.

### 3. \`release.yml\` (Tags)
* Validates full CI suite.
* Publishes to PyPI using **Trusted Publishing (OIDC)**, completely removing the need for long-lived repository secrets.
        `
    };

    // SPA Logic
    const nodes = {
        navItems: document.querySelectorAll('.nav-item'),
        pageContent: document.getElementById('page-content'),
        markdownContainer: document.getElementById('markdown-container'),
        playgroundContent: document.getElementById('playground-content'),
        
        // Playground specific nodes
        projectRoot: document.getElementById("project-root"),
        refreshStatus: document.getElementById("refresh-status"),
        chatThread: document.getElementById("chat-thread"),
        composerInput: document.getElementById("composer-input"),
        composerDispatch: document.getElementById("composer-dispatch"),
        composerSubmit: document.getElementById("composer-submit"),
        composerHint: document.getElementById("composer-hint"),
        chatComposer: document.getElementById("chat-composer"),
        runSummaryId: document.getElementById("run-summary-id"),
        runSummaryStatusPill: document.getElementById("run-summary-status-pill"),
        runSummaryStatusDot: document.getElementById("run-summary-status-dot"),
        runSummaryStatus: document.getElementById("run-summary-status"),
        runOpStatus: document.getElementById("run-op-status"),
        runWorkers: document.getElementById("run-workers"),
        taskCount: document.getElementById("task-count"),
        taskList: document.getElementById("task-list"),
    };

    function navigate(route) {
        window.location.hash = route;
        renderRoute(route);
    }

    function renderRoute(route) {
        route = route.replace('#', '') || 'overview';
        
        // Update nav styling
        nodes.navItems.forEach(el => el.classList.remove('active'));
        const activeNav = document.getElementById('nav-' + route);
        if (activeNav) activeNav.classList.add('active');

        // Toggle visibility
        if (route === 'playground') {
            nodes.pageContent.classList.add('hidden');
            nodes.playgroundContent.classList.remove('hidden');
            nodes.playgroundContent.classList.add('flex');
        } else {
            nodes.playgroundContent.classList.add('hidden');
            nodes.playgroundContent.classList.remove('flex');
            nodes.pageContent.classList.remove('hidden');
            
            const rawMarkdown = docs[route] || '# Not Found\nThe requested documentation page does not exist.';
            const html = DOMPurify.sanitize(marked.parse(rawMarkdown));
            nodes.markdownContainer.innerHTML = html;
        }
    }

    // Initialize router
    window.addEventListener('hashchange', () => renderRoute(window.location.hash));
    renderRoute(window.location.hash || 'overview');


    // -----------------------------------------------------
    // PLAYGROUND FUNCTIONALITY (Ported from existing)
    // -----------------------------------------------------
    const state = { payload: null, activeRunId: null, busy: false };
    const ACTIVE_ATTEMPTS = new Set(["dispatching", "running", "paused", "needs_input"]);

    function escapeHtml(value) {
        return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
    }

    function activeRun() {
        if (!state.payload || !Array.isArray(state.payload.runs)) return null;
        return state.payload.runs.find((item) => item.id === state.activeRunId) || state.payload.selected_run || state.payload.runs[0] || null;
    }

    function openHumanRequest(run) {
        return (run?.human_requests || []).find((item) => item.status === "open") || null;
    }

    function openApprovals(run) {
        return (run?.approval_requests || []).filter((item) => item.status === "requested");
    }

    function resolveApprovalHTML(request) {
        return `
        <div class="mt-2 p-3 bg-card border border-borderSubtle rounded-md">
            <strong class="block text-textMain text-xs font-mono mb-1">Approval Requested:</strong>
            <p class="text-textMuted text-xs font-sans mb-3">${escapeHtml(request.reason)}</p>
            <div class="flex gap-2">
                <button type="button" class="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-sm font-mono text-xs transition-colors" onclick="window.resolveApproval('${request.runId}', '${request.id}', true)">Approve</button>
                <button type="button" class="border border-red-500/50 text-red-400 hover:bg-red-500/10 px-3 py-1.5 rounded-sm font-mono text-xs transition-colors" onclick="window.resolveApproval('${request.runId}', '${request.id}', false)">Reject</button>
            </div>
        </div>
        `;
    }

    function renderFeed(run) {
        const messages = run ? (run.chat_messages || []) : [];
        let html = "";
        
        if (!messages.length) {
            nodes.chatThread.innerHTML = `<div class="empty"><span class="material-symbols-outlined text-[32px] mb-2 text-borderSubtle">forum</span><p class="text-textMuted text-xs">No chat history for this run.</p></div>`;
            return;
        }

        messages.forEach(msg => {
            let roleTag = "[SYS]";
            let textColor = "text-textMuted";
            let bgClass = "transparent";
            
            if (msg.role === "user") {
                roleTag = "[YOU]";
                textColor = "text-textMain";
                bgClass = "bg-card border border-borderSubtle p-2.5 rounded-sm";
            } else if (msg.role === "manager") {
                roleTag = "[ AI]";
                textColor = "text-textMuted";
            }

            html += `
            <div class="flex gap-3 mb-4">
                <span class="text-textMuted font-bold w-12 shrink-0">${roleTag}</span>
                <div class="flex-1 ${bgClass}">
                    <p class="${textColor} whitespace-pre-wrap">${escapeHtml(msg.text)}</p>
                </div>
            </div>`;
        });

        if (run) {
            const approvals = openApprovals(run);
            approvals.forEach(appr => {
                appr.runId = run.id;
                html += `
                <div class="flex gap-3 mb-4">
                    <span class="text-amber-500 font-bold w-12 shrink-0">[REQ]</span>
                    <div class="flex-1">
                        ${resolveApprovalHTML(appr)}
                    </div>
                </div>`;
            });
        }

        nodes.chatThread.innerHTML = html;
        nodes.chatThread.scrollTop = nodes.chatThread.scrollHeight;

        const hr = openHumanRequest(run);
        nodes.composerHint.textContent = hr ? \`Answering clarification: \${hr.question}\` : "";
    }

    function renderExecution(run) {
        if (!run) {
            nodes.runSummaryId.textContent = "No Active Run";
            nodes.runSummaryStatus.textContent = "Idle";
            nodes.runOpStatus.textContent = "-";
            nodes.runWorkers.textContent = "0";
            nodes.taskCount.textContent = "0 tasks";
            nodes.taskList.innerHTML = `<div class="empty"><span class="material-symbols-outlined text-[32px] mb-2 text-borderSubtle">analytics</span><p class="text-textMuted font-mono text-[10px]">Awaiting Workflow Execution</p></div>`;
            return;
        }

        nodes.runSummaryId.textContent = escapeHtml(run.id || run.title);
        nodes.runSummaryStatus.textContent = escapeHtml(run.execution_status || "Unknown");
        nodes.runOpStatus.textContent = escapeHtml(run.operator_status || "Unknown");
        
        let attempts = (run.attempts || []).filter(a => ACTIVE_ATTEMPTS.has(a.state));
        nodes.runWorkers.textContent = attempts.length.toString();

        const isRunning = run.execution_status === "running" || run.execution_status === "dispatching";
        if (isRunning) {
            nodes.runSummaryStatusPill.className = "flex items-center gap-2 px-2 py-0.5 rounded-sm bg-amber-500/10 border border-amber-500/20";
            nodes.runSummaryStatusDot.className = "w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse";
            nodes.runSummaryStatus.className = "text-[10px] font-mono text-amber-500 uppercase font-bold";
        } else if (run.execution_status === "completed" || run.execution_status === "succeeded") {
            nodes.runSummaryStatusPill.className = "flex items-center gap-2 px-2 py-0.5 rounded-sm bg-emerald-500/10 border border-emerald-500/20";
            nodes.runSummaryStatusDot.className = "w-1.5 h-1.5 rounded-full bg-emerald-500";
            nodes.runSummaryStatus.className = "text-[10px] font-mono text-emerald-500 uppercase font-bold";
        } else {
            nodes.runSummaryStatusPill.className = "flex items-center gap-2 px-2 py-0.5 rounded-sm bg-borderSubtle/50 border border-borderSubtle";
            nodes.runSummaryStatusDot.className = "w-1.5 h-1.5 rounded-full bg-textMuted";
            nodes.runSummaryStatus.className = "text-[10px] font-mono text-textMuted uppercase font-bold";
        }

        const tasks = run.tasks || [];
        nodes.taskCount.textContent = \`\${tasks.length} tasks\`;

        let tasksHtml = "";
        tasks.forEach(task => {
            let icon = "pending";
            let iconClass = "text-textMuted";
            let taskBg = "opacity-50 grayscale hover:grayscale-0 hover:opacity-100 transition-all border-b border-borderSubtle";
            let stateLabel = escapeHtml(task.state);
            let stateColor = "text-textMuted";
            
            if (task.state === "succeeded" || task.state === "completed") {
                icon = "check_circle";
                iconClass = "text-emerald-500";
                taskBg = "hover:bg-card transition-colors border-b border-borderSubtle";
                stateColor = "text-emerald-500";
            } else if (task.state === "running" || task.state === "dispatching") {
                icon = "refresh";
                iconClass = "text-amber-500 animate-spin";
                taskBg = "bg-amber-500/5 relative overflow-hidden border-b border-borderSubtle";
                stateColor = "text-amber-500";
                tasksHtml += `<div class="absolute left-0 top-0 bottom-0 w-0.5 bg-amber-500"></div>`; 
            } else if (task.state === "failed" || task.state === "error") {
                icon = "error";
                iconClass = "text-red-500";
                taskBg = "bg-red-500/5 border-b border-red-500/20";
                stateColor = "text-red-500";
            }

            tasksHtml += `
            <div class="p-3 flex items-start gap-3 \${taskBg} relative">
                <div class="mt-0.5"><span class="material-symbols-outlined \${iconClass}" style="font-size: 16px;">\${icon}</span></div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center justify-between gap-2">
                        <h4 class="text-xs font-semibold text-textMain truncate">\${escapeHtml(task.title || task.task_key)}</h4>
                        <span class="text-[10px] font-mono font-bold uppercase tracking-wider \${stateColor}">\${stateLabel}</span>
                    </div>
                    <p class="text-[11px] text-textMuted mt-1 line-clamp-2">\${escapeHtml(task.worker_summary || "No description")}</p>
                    <div class="mt-2 flex items-center gap-2">
                        <span class="px-1.5 py-0.5 rounded-sm bg-borderSubtle/50 text-textMuted font-mono text-[9px] uppercase border border-borderSubtle">\${escapeHtml(task.task_key)}</span>
                    </div>
                </div>
            </div>`;
        });

        if (!tasks.length) {
            tasksHtml = `<div class="empty"><span class="material-symbols-outlined text-[32px] mb-2 text-borderSubtle">analytics</span><p class="text-textMuted font-mono text-[10px]">End of Pipeline</p></div>`;
        }

        nodes.taskList.innerHTML = tasksHtml;
    }

    function renderPlayground() {
        nodes.refreshStatus.innerHTML = state.payload ? 
            '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Connected' : 
            '<span class="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span> Disconnected';
        
        const run = activeRun();
        renderFeed(run);
        renderExecution(run);
    }

    async function postJson(path, payload) {
        const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        if (!response.ok) throw new Error(await response.text() || \`\${path} failed\`);
        return await response.json();
    }

    async function loadState() {
        if (state.busy) return;
        state.busy = true;
        try {
            const response = await fetch("/api/state?limit=8", { cache: "no-store" });
            const payload = await response.json();
            state.payload = payload;
            const runIds = new Set((payload.runs || []).map((run) => run.id));
            if (!state.activeRunId || !runIds.has(state.activeRunId)) {
                state.activeRunId = payload.selected_run_id || payload.selected_run?.id || payload.runs?.[0]?.id || null;
            }
            if (window.location.hash.includes("playground")) {
                renderPlayground();
            }
        } catch (error) {
            if (window.location.hash.includes("playground")) {
                nodes.refreshStatus.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span> Disconnected';
            }
        } finally {
            state.busy = false;
        }
    }

    window.resolveApproval = async function(workflowRunId, approvalRequestId, approved) {
        try {
            await postJson("/api/approval", {
                workflow_run_id: workflowRunId,
                approval_request_id: approvalRequestId,
                approved,
                dispatch: nodes.composerDispatch.value === "true",
                max_steps: 8,
            });
            await loadState();
        } catch (error) {
            nodes.composerHint.textContent = \`Error: \${error.message}\`;
        }
    };

    async function submitComposer(event) {
        event.preventDefault();
        const message = nodes.composerInput.value.trim();
        if (!message) return;
        
        const run = activeRun();
        const hr = openHumanRequest(run);
        const payload = { message, dispatch: nodes.composerDispatch.value === "true", max_steps: 8 };
        if (run && hr) {
            payload.workflow_run_id = run.id;
            payload.human_request_id = hr.id;
        }
        nodes.composerSubmit.disabled = true;
        nodes.composerInput.value = "";
        nodes.composerHint.textContent = "Sending...";
        try {
            await postJson("/api/chat", payload);
            nodes.composerHint.textContent = "";
            await loadState();
        } catch (error) {
            nodes.composerHint.textContent = \`Error: \${error.message}\`;
        } finally {
            nodes.composerSubmit.disabled = false;
        }
    }

    nodes.chatComposer.addEventListener("submit", submitComposer);
    
    // Initial fetch
    loadState();
    window.setInterval(loadState, 4000);
</script>
</body>
</html>"""
