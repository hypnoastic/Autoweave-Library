"""HTML shell for the lightweight AutoWeave operator console and docs playground."""

from __future__ import annotations


def render_dashboard_page() -> str:
    return r"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="utf-8"/>
    <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
    <title>AutoWeave Library | Console</title>
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL,GRAD,opsz@400,0,0,24&display=swap" rel="stylesheet"/>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet"/>
    <link href="https://cdn.jsdelivr.net/gh/vernnont/geist-font@v1.0.1/geist.css" rel="stylesheet"/>
    
    <style>
        :root {
            --bg-base: #09090b;
            --bg-surface: #0f0f12;
            --bg-elevated: #18181b;
            --border-default: #27272a;
            --border-subtle: #1e1e21;
            --text-primary: #fafafa;
            --text-secondary: #a1a1aa;
            --text-tertiary: #71717a;
            --accent: #fafafa;
            --accent-dim: rgba(250, 250, 250, 0.1);
            --success: #22c55e;
            --success-dim: rgba(34, 197, 94, 0.1);
            --warning: #eab308;
            --warning-dim: rgba(234, 179, 8, 0.1);
            --danger: #ef4444;
            --danger-dim: rgba(239, 68, 68, 0.1);
            --font-sans: 'Geist', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-base);
            color: var(--text-primary);
            font-family: var(--font-sans);
            font-size: 14px;
            line-height: 1.5;
            height: 100vh;
            width: 100vw;
            overflow: hidden;
            display: flex;
        }

        a {
            color: inherit;
            text-decoration: none;
        }

        /* --- Scrollbar --- */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border-default); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-tertiary); }

        /* --- Loading Screen --- */
        #loading-screen {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-color: var(--bg-base);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 9999;
            transition: opacity 0.4s ease, visibility 0.4s;
        }
        #loading-screen.hidden {
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
        }
        .logo-container {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 32px;
        }
        .logo-icon {
            width: 32px;
            height: 32px;
            background: var(--text-primary);
            color: var(--bg-base);
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 6px;
        }
        .logo-text {
            font-size: 20px;
            font-weight: 600;
            letter-spacing: -0.02em;
        }
        .progress-container {
            width: 240px;
            height: 4px;
            background: var(--bg-elevated);
            border-radius: 2px;
            overflow: hidden;
            margin-bottom: 16px;
        }
        .progress-bar {
            height: 100%;
            width: 0%;
            background: var(--accent);
            transition: width 0.3s ease;
        }
        .status-text {
            color: var(--text-secondary);
            font-family: var(--font-mono);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        /* --- Main Layout --- */
        #app {
            display: flex;
            width: 100%;
            height: 100%;
            opacity: 0;
            transition: opacity 0.5s ease;
        }
        #app.visible {
            opacity: 1;
        }

        /* --- Sidebar --- */
        .sidebar {
            width: 240px;
            border-right: 1px solid var(--border-default);
            background-color: var(--bg-base);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }
        .sidebar-header {
            padding: 24px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .sidebar-header .icon {
            width: 28px;
            height: 28px;
            background: var(--text-primary);
            color: var(--bg-base);
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 4px;
        }
        .sidebar-header .title {
            font-size: 14px;
            font-weight: 600;
            letter-spacing: -0.01em;
        }
        .sidebar-header .version {
            font-size: 10px;
            font-family: var(--font-mono);
            color: var(--text-secondary);
        }
        
        .nav-group {
            margin-top: 24px;
            padding: 0 16px;
        }
        .nav-title {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-tertiary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 8px;
            padding: 0 8px;
        }
        .nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px;
            border-radius: 6px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.2s;
            border-left: 2px solid transparent;
        }
        .nav-item:hover {
            color: var(--text-primary);
            background: var(--bg-surface);
        }
        .nav-item.active {
            color: var(--text-primary);
            background: var(--bg-elevated);
            border-left: 2px solid var(--accent);
            font-weight: 500;
        }
        .nav-item .material-symbols-outlined {
            font-size: 18px;
        }

        .sidebar-footer {
            margin-top: auto;
            padding: 16px 24px;
            border-top: 1px solid var(--border-default);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 6px;
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--text-secondary);
        }
        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--text-tertiary);
        }
        .status-dot.connected {
            background: var(--success);
            box-shadow: 0 0 4px var(--success);
        }
        .status-dot.disconnected {
            background: var(--danger);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }

        /* --- Main Content Area --- */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            position: relative;
            background: var(--bg-base);
        }

        /* Page Container */
        .page-container {
            display: none;
            width: 100%;
            height: 100%;
            overflow-y: auto;
        }
        .page-container.active {
            display: flex;
        }

        
        /* Runs Page */
        .runs-list {
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .run-item {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 16px;
            cursor: pointer;
            transition: border-color 0.2s;
        }
        .run-item:hover {
            border-color: var(--border-hover);
        }
        .run-item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .run-item-details {
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--border-default);
            display: none;
        }
        .run-item.expanded .run-item-details {
            display: block;
        }

        /* Agent Right Sidebar */
        .agent-sidebar {
            position: fixed;
            right: -400px;
            top: 0;
            width: 400px;
            height: 100%;
            background: var(--bg-surface);
            border-left: 1px solid var(--border-default);
            transition: right 0.3s ease;
            z-index: 100;
            padding: 24px;
            overflow-y: auto;
            box-shadow: -4px 0 16px rgba(0,0,0,0.2);
        }
        .agent-sidebar.open {
            right: 0;
        }
        .agent-sidebar-close {
            position: absolute;
            top: 24px;
            right: 24px;
            cursor: pointer;
            color: var(--text-secondary);
        }
        .agent-sidebar-close:hover {
            color: var(--text-primary);
        }
        .agent-live-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: rgba(34, 197, 94, 0.1);
            color: #22c55e;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 8px;
            border: 1px solid rgba(34, 197, 94, 0.2);
        }
        .agent-live-badge .pulse-dot {
            width: 6px;
            height: 6px;
            background: #22c55e;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        
        /* Docs layout */
        .docs-layout {
            /* display flex provided by active class */
            width: 100%;
            height: 100%;
        }
        .docs-sidebar {
            width: 250px;
            border-right: 1px solid var(--border-default);
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .docs-sidebar input {
            width: 100%;
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            color: var(--text-primary);
            padding: 8px 12px;
            border-radius: 6px;
            font-family: var(--font-sans);
            font-size: 13px;
        }
        .docs-content {
            flex: 1;
            padding: 32px 48px;
            overflow-y: auto;
        }

        /* Prose Content (Docs) */
        .prose-content {
            max-width: 768px;
            margin: 0 auto;
            padding: 48px 32px;
            width: 100%;
        }
        .markdown-body h1 {
            font-size: 32px;
            font-weight: 600;
            letter-spacing: -0.02em;
            margin-bottom: 24px;
            color: var(--text-primary);
        }
        .markdown-body h2 {
            font-size: 20px;
            font-weight: 600;
            letter-spacing: -0.01em;
            margin-top: 40px;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-default);
        }
        .markdown-body h3 {
            font-size: 16px;
            font-weight: 600;
            margin-top: 32px;
            margin-bottom: 12px;
        }
        .markdown-body p {
            margin-bottom: 16px;
            color: var(--text-secondary);
            font-size: 15px;
        }
        .markdown-body a {
            color: var(--text-primary);
            text-decoration: underline;
            text-underline-offset: 2px;
        }
        .markdown-body ul, .markdown-body ol {
            margin-bottom: 16px;
            padding-left: 24px;
            color: var(--text-secondary);
        }
        .markdown-body li {
            margin-bottom: 8px;
        }
        .markdown-body code:not(pre code) {
            font-family: var(--font-mono);
            font-size: 13px;
            background: var(--bg-elevated);
            padding: 2px 6px;
            border-radius: 4px;
            border: 1px solid var(--border-subtle);
        }
        .markdown-body pre {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
            overflow-x: auto;
            position: relative;
        }
        .markdown-body pre code {
            font-family: var(--font-mono);
            font-size: 13px;
            color: var(--text-secondary);
            background: transparent;
            padding: 0;
            border: none;
        }

        /* --- Playground View --- */
        .playground-layout {
            width: 100%;
            height: 100%;
        }
        .pane-chat {
            flex: 1;
            display: flex;
            flex-direction: column;
            border-right: 1px solid var(--border-default);
        }
        .pane-dag {
            width: 400px;
            display: flex;
            flex-direction: column;
            background: var(--bg-surface);
            flex-shrink: 0;
        }
        .pane-header {
            height: 56px;
            padding: 0 16px;
            border-bottom: 1px solid var(--border-default);
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
            background: var(--bg-base);
        }
        .pane-title {
            font-size: 13px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Chat UI */
        .chat-thread {
            flex: 1;
            overflow-y: auto;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }
        .chat-msg {
            display: flex;
            gap: 16px;
        }
        .msg-role {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 600;
            width: 48px;
            flex-shrink: 0;
            padding-top: 2px;
        }
        .msg-content {
            flex: 1;
            font-family: var(--font-mono);
            font-size: 13px;
        }
        .msg-sys { color: var(--text-tertiary); }
        .msg-user { color: var(--text-primary); }
        .msg-user .msg-content {
            background: var(--bg-elevated);
            padding: 12px;
            border-radius: 6px;
            border: 1px solid var(--border-subtle);
        }
        
        .chat-input {
            padding: 16px;
            border-top: 1px solid var(--border-default);
            background: var(--bg-surface);
        }
        .input-box {
            display: flex;
            align-items: center;
            background: var(--bg-base);
            border: 1px solid var(--border-default);
            border-radius: 6px;
            padding: 8px 12px;
            gap: 12px;
        }
        .input-box:focus-within {
            border-color: var(--text-tertiary);
        }
        .input-box input {
            flex: 1;
            background: transparent;
            border: none;
            outline: none;
            color: var(--text-primary);
            font-family: var(--font-mono);
            font-size: 13px;
        }
        .input-box button {
            background: var(--text-primary);
            color: var(--bg-base);
            border: none;
            border-radius: 4px;
            padding: 4px 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .input-box button:hover {
            opacity: 0.9;
        }
        .input-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 4px 0;
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-secondary);
        }
        .input-meta select {
            background: transparent;
            border: 1px solid var(--border-default);
            color: var(--text-primary);
            border-radius: 4px;
            padding: 2px 4px;
            outline: none;
        }

        /* Execution DAG UI */
        .dag-summary {
            padding: 16px;
            border-bottom: 1px solid var(--border-default);
            background: var(--bg-base);
        }
        .dag-meta {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 16px;
        }
        .dag-title {
            font-family: var(--font-mono);
            font-size: 14px;
            font-weight: 600;
        }
        .dag-label {
            font-size: 10px;
            text-transform: uppercase;
            font-weight: 600;
            color: var(--text-tertiary);
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }
        .status-pill {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 2px 8px;
            border-radius: 12px;
            border: 1px solid var(--border-default);
            font-family: var(--font-mono);
            font-size: 10px;
            text-transform: uppercase;
            font-weight: 600;
        }
        .pill-idle { border-color: var(--border-default); color: var(--text-secondary); }
        .pill-idle .dot { background: var(--text-tertiary); }
        
        .pill-running { border-color: var(--warning-dim); background: var(--warning-dim); color: var(--warning); }
        .pill-running .dot { background: var(--warning); animation: pulse 1.5s infinite; }
        
        .pill-success { border-color: var(--success-dim); background: var(--success-dim); color: var(--success); }
        .pill-success .dot { background: var(--success); }
        
        .pill-failed { border-color: var(--danger-dim); background: var(--danger-dim); color: var(--danger); }
        .pill-failed .dot { background: var(--danger); }

        .dag-stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }
        .stat-box {
            background: var(--bg-base);
            border: 1px solid var(--border-default);
            padding: 12px;
            border-radius: 6px;
        }
        .stat-val {
            font-family: var(--font-mono);
            font-size: 13px;
        }

        .task-list {
            flex: 1;
            overflow-y: auto;
            background: var(--bg-base);
        }
        .task-item {
            padding: 16px;
            border-bottom: 1px solid var(--border-default);
            display: flex;
            gap: 12px;
        }
        .task-item.running {
            background: var(--bg-surface);
            border-left: 2px solid var(--warning);
        }
        .task-icon {
            margin-top: 2px;
        }
        .task-content {
            flex: 1;
            min-width: 0;
        }
        .task-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
        }
        .task-name {
            font-size: 13px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .task-state {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .state-pending { color: var(--text-tertiary); }
        .state-running { color: var(--warning); }
        .state-success { color: var(--success); }
        .state-failed { color: var(--danger); }
        
        .task-desc {
            font-size: 12px;
            color: var(--text-secondary);
            margin-bottom: 8px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .task-key {
            display: inline-block;
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--text-tertiary);
            border: 1px solid var(--border-default);
            padding: 2px 6px;
            border-radius: 4px;
        }

        /* Alerts (Approvals) */
        .approval-card {
            background: var(--bg-elevated);
            border: 1px solid var(--border-default);
            border-radius: 6px;
            padding: 16px;
            margin-top: 8px;
        }
        .approval-title {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 600;
            color: var(--warning);
            margin-bottom: 8px;
        }
        .approval-actions {
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }
        .btn {
            font-family: var(--font-mono);
            font-size: 12px;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            border: none;
            transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.9; }
        .btn-approve { background: var(--success); color: var(--bg-base); }
        .btn-reject { background: transparent; border: 1px solid var(--danger); color: var(--danger); }

        /* Empty States */
        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-tertiary);
            text-align: center;
            padding: 32px;
        }
        .empty-state .material-symbols-outlined {
            font-size: 32px;
            margin-bottom: 12px;
        }

        /* Agents Grid */
        .agents-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 24px;
            padding: 24px 32px;
        }
        .agent-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-default);
            border-radius: 8px;
            padding: 20px;
            display: flex;
            flex-direction: column;
        }
        .agent-role {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--accent);
            text-transform: uppercase;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .agent-name {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 12px;
        }
        .agent-desc {
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 16px;
            flex: 1;
        }
        .agent-skills {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .skill-tag {
            background: var(--bg-elevated);
            border: 1px solid var(--border-subtle);
            color: var(--text-secondary);
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 12px;
        }

        /* Utils */
        .hidden { display: none !important; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({ startOnLoad: false, theme: "dark" });
    </script>
</head>
<body>

    <!-- Loading Screen -->
    <div id="loading-screen">
        <div class="logo-container">
            <div class="logo-icon">
                <span class="material-symbols-outlined" style="font-size: 20px;">terminal</span>
            </div>
            <div class="logo-text">AutoWeave</div>
        </div>
        <div class="progress-container">
            <div id="loading-progress" class="progress-bar"></div>
        </div>
        <div id="loading-status" class="status-text">INITIALIZING...</div>
    </div>

    <!-- Main App -->
    <div id="app">
        <!-- Sidebar -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <div class="icon">
                    <span class="material-symbols-outlined" style="font-size: 18px;">terminal</span>
                </div>
                <div>
                    <div class="title">AutoWeave</div>
                    <div class="version">Library • v2.4.0</div>
                </div>
            </div>

            <div class="nav-group" style="margin-top: 12px;">
                <a class="nav-item active" data-route="playground">
                    <span class="material-symbols-outlined">play_circle</span> Playground
                </a>
                <a class="nav-item" data-route="runs">
                    <span class="material-symbols-outlined">list_alt</span> Runs
                </a>
                <a class="nav-item" data-route="agents">
                    <span class="material-symbols-outlined">smart_toy</span> Agents
                </a>
                <a class="nav-item" data-route="docs">
                    <span class="material-symbols-outlined">menu_book</span> Docs
                </a>
            </div>

            <div class="sidebar-footer">
                <div class="status-indicator">
                    <div id="connection-dot" class="status-dot disconnected"></div>
                    <span id="connection-text">Connecting...</span>
                </div>
            </div>
        </aside>

        <!-- Main Content -->
        <main class="main-content">
            <!-- Docs Pages -->
            <div id="page-docs" class="page-container active docs-layout">
                <div class="docs-sidebar">
                    <div style="font-weight: 600; font-size: 14px; margin-bottom: 8px;">Documentation</div>
                    <input type="text" id="docs-search" placeholder="Search docs..." />
                    <div class="nav-group" style="padding-top: 8px;" id="docs-nav-group">
                        <a class="nav-item active" data-doc="ARCHITECTURE">Architecture</a>
                        <a class="nav-item" data-doc="DEPLOYMENT">Deployment</a>
                        <a class="nav-item" data-doc="autoweave_diagrams_source">Diagrams Source</a>
                        <a class="nav-item" data-doc="autoweave_high_level_architecture">High Level Architecture</a>
                        <a class="nav-item" data-doc="autoweave_implementation_spec">Implementation Spec</a>
                    </div>
                </div>
                <div class="docs-content">
                    <div class="prose-content markdown-body" id="markdown-container">
                        <!-- Markdown rendered here -->
                    </div>
                </div>
            </div>

            <!-- Runs Page -->
            <div id="page-runs" class="page-container">
                <div style="width: 100%;">
                    <div style="padding: 32px 32px 0;">
                        <h1 style="font-size: 24px; font-weight: 600; margin-bottom: 8px;">Execution Runs</h1>
                        <p style="color: var(--text-secondary); font-size: 14px;">Historical workflow executions and processes.</p>
                    </div>
                    <div id="runs-list" class="runs-list">
                        <!-- Runs rendered here -->
                    </div>
                </div>
            </div>

            <!-- Agents Page -->
            <div id="page-agents" class="page-container">
                <div style="width: 100%;">
                    <div style="padding: 32px 32px 0;">
                        <h1 style="font-size: 24px; font-weight: 600; margin-bottom: 8px;">Configured Agents</h1>
                        <p style="color: var(--text-secondary); font-size: 14px;">The active AI agents available to execute tasks in your workflow blueprint.</p>
                    </div>
                    <div id="agents-grid" class="agents-grid">
                        <!-- Agent cards rendered here -->
                    </div>
                </div>
            </div>
            
            <div id="agent-sidebar" class="agent-sidebar">
                <span class="material-symbols-outlined agent-sidebar-close" onclick="document.getElementById('agent-sidebar').classList.remove('open')">close</span>
                <div id="agent-sidebar-content"></div>
            </div>

            <!-- Playground Page -->
            <div id="page-playground" class="page-container playground-layout">
                <!-- Chat Pane -->
                <div class="pane-chat">
                    <div class="pane-header">
                        <div class="pane-title">
                            <span class="material-symbols-outlined" style="color: var(--text-secondary); font-size: 18px;">forum</span>
                            Manager Chat
                        </div>
                        <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-secondary); display: flex; align-items: center; gap: 6px;">
                            <span style="display: block; width: 6px; height: 6px; border-radius: 50%; background: var(--text-primary); animation: pulse 2s infinite;"></span>
                            LIVE FEED
                        </div>
                    </div>
                    
                    <div id="chat-thread" class="chat-thread">
                        <!-- Chat messages rendered here -->
                    </div>

                    <form id="chat-composer" class="chat-input">
                        <div class="input-box">
                            <span style="font-family: var(--font-mono); color: var(--text-tertiary);">$</span>
                            <input id="composer-input" type="text" placeholder="Send command or request..." autocomplete="off"/>
                            <button id="composer-submit" type="submit">
                                <span class="material-symbols-outlined" style="font-size: 18px;">send</span>
                            </button>
                        </div>
                        <div class="input-meta">
                            <label>
                                Mode: 
                                <select id="composer-dispatch">
                                    <option value="true" selected>Live Execution</option>
                                    <option value="false">Dry Run</option>
                                </select>
                            </label>
                            <span id="composer-hint"></span>
                        </div>
                    </form>
                </div>

                <!-- DAG Pane -->
                <div class="pane-dag">
                    <div class="dag-summary">
                        <div class="dag-meta">
                            <div>
                                <div class="dag-label">Current Run</div>
                                <div id="run-summary-id" class="dag-title">No Active Run</div>
                            </div>
                            <div id="run-summary-pill" class="status-pill pill-idle">
                                <div id="run-summary-dot" class="dot" style="width: 6px; height: 6px; border-radius: 50%;"></div>
                                <span id="run-summary-status">IDLE</span>
                            </div>
                        </div>
                        <div class="dag-stats">
                            <div class="stat-box">
                                <div class="dag-label">Operator</div>
                                <div id="run-op-status" class="stat-val">-</div>
                            </div>
                            <div class="stat-box">
                                <div class="dag-label">Active Workers</div>
                                <div id="run-workers" class="stat-val">0</div>
                            </div>
                        </div>
                    </div>
                    
                    <div style="padding: 8px 16px; border-bottom: 1px solid var(--border-default); display: flex; justify-content: space-between; align-items: center; background: var(--bg-base);">
                        <span class="dag-label" style="margin: 0;">Execution DAG</span>
                        <span id="task-count" style="font-family: var(--font-mono); font-size: 10px; color: var(--text-tertiary);">0 tasks</span>
                    </div>

                    <div id="task-list" class="task-list">
                        <!-- Tasks rendered here -->
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        /* --- Simple Markdown Parser --- */
        function parseMarkdown(md) {
            if (!md) return '';
            
            // Protect code blocks first
            const codeBlocks = [];
            let html = md.replace(/```([a-z]+)?\n([\s\S]*?)```/g, (match, lang, code) => {
                codeBlocks.push({ lang: lang || '', code: code.replace(/</g, '&lt;').replace(/>/g, '&gt;') });
                return `__CODE_BLOCK_${codeBlocks.length - 1}__`;
            });
            
            // Inline code
            html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
            
            // Headers
            html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
            html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
            html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
            
            // Bold & Italic
            html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
            
            // Links
            html = html.replace(/\[([^]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
            
            // Lists (Simple)
            html = html.replace(/^\* (.*$)/gim, '<ul><li>$1</li></ul>');
            html = html.replace(/<\/ul>\n<ul>/g, ''); // merge adjacent lists
            
            // Paragraphs
            html = html.replace(/^([^<\s].*)$/gim, '<p>$1</p>');
            
            // Restore code blocks
            html = html.replace(/__CODE_BLOCK_(\d+)__/g, (match, index) => {
                const block = codeBlocks[index];
                if (block.lang === 'mermaid') {
                    const rawCode = block.code.replace(/&lt;/g, '<').replace(/&gt;/g, '>');
                    return `<div class="mermaid">${rawCode}</div>`;
                }
                return `<pre><code class="language-${block.lang}">${block.code}</code></pre>`;
            });
            
            // Clean up empty paragraphs
            html = html.replace(/<p><\/p>/g, '');
            
            return html;
        }

        /* --- Content Store --- */
        const docs = {
            'ARCHITECTURE': `
# AutoWeave High-Level Architecture

Version: 2.0  
Status: frozen architecture baseline  
Primary runtime: **OpenHands agent-server remote workers**  
Primary model platform: **Google Vertex AI**  
Primary operator surface: **terminal-first application / library-first control plane**

---

## 1. Executive Summary

AutoWeave is a **multi-agent orchestration and control-plane library**.

It is not a clone of OpenHands, and it is not a thin wrapper around OpenHands.

The system is split deliberately:

- **AutoWeave** owns orchestration, workflow state, task graphs, approvals, context and memory services, artifact routing, model routing, observability, auditability, and policy.
- **OpenHands** owns single-agent execution inside an isolated remote sandbox/workspace: tool use, file editing, command execution, local skill loading, and step-level agent behavior.

The key architecture decisions are:

1. **OpenHands runs through agent-server remote workers**. Embedded local mode may exist for developer convenience, but remote workers are the production architecture.
2. **AutoWeave owns the canonical schema**. AutoWeave compiles canonical agent/task/runtime state into OpenHands-facing run config.
3. **Vertex AI is the primary model platform**. Credentials are injected into workers by the AutoWeave runtime; agents do not log in interactively.
4. **PostgreSQL is the source of truth** for durable state.
5. **Redis + Celery** provide ephemeral coordination, queues, leases, heartbeats, and background execution.
6. **Neo4j is included** for both relationship traversal and graph-oriented retrieval, but it is still downstream of canonical truth.
7. **Agents retrieve context through tools/services**, not by receiving giant prepacked prompts.
8. **One sandbox/worktree per task attempt** is the default.
9. **Dynamic parallelism is orchestrator-controlled**. Independent branches fan out automatically when dependencies and policy allow.
10. **Observability is exported through AutoWeave-normalized events, spans, and metrics**, not by exposing raw OpenHands internals directly to the main product.

---

## 2. Product Goals

### Goals

1. Orchestrate specialized agents as one coherent engineering team.
2. Keep durable system truth outside worker-local state.
3. Support dynamic task decomposition, dependency-aware scheduling, human clarification, approvals, retries, and resumability.
4. Provide precise context retrieval and memory layers without uncontrolled prompt bloat.
5. Preserve full provenance: which agent did what, when, with which inputs, outputs, and approvals.
6. Expose clean telemetry and history to a future main product.
7. Start coding-first while remaining extensible to non-coding workflows later.

### Non-goals

1. Rebuild OpenHands' internal reasoning and tool loop.
2. Use a shared mutable workspace for all agents.
3. Give agents raw SQL or raw graph query access.
4. Depend on worker-local file persistence as the distributed source of truth.
5. Make peer-to-peer free-form chat the main coordination mechanism.
6. Build the product UI in phase one.

---

## 3. System Context

\`\`\`mermaid
flowchart TD
    H[Human / Main Product / CLI] --> O[AutoWeave Orchestrator]
    O --> CC[Config Compiler]
    O --> CS[Context Service]
    O --> AR[Artifact Registry]
    O --> AP[Approval Service]
    O --> EV[Observability Service]
    O --> PG[(Postgres + pgvector)]
    O --> RD[(Redis)]
    O --> CY[Celery]
    O --> N4[(Neo4j)]
    O --> OH[OpenHands Remote Workers]
    OH --> SB[Isolated sandbox/worktree]
    OH --> VX[Vertex AI]
\`\`\`

---

## 4. Storage Architecture

AutoWeave relies on a polyglot persistence architecture to handle different workloads efficiently.

### Source of Truth: PostgreSQL
All canonical state resides in PostgreSQL. This includes:
- Workflow Definitions and Runs
- Tasks and Task Attempts
- Domain Events (Event Sourced log)
- Artifact Metadata
- Approvals and Human Requests

### Queue & Ephemeral State: Redis
Used for:
- Celery Task Queues
- Distributed Locks and Leases
- Ephemeral Heartbeats

### Vector & Semantic Search: pgvector
Used to index and search textual context quickly based on embeddings.

### Graph Projections: Neo4j
Graph structures (Task DAGs, Artifact provenance, memory associations) are projected asynchronously to Neo4j. It answers graph-traversal queries that are inefficient in SQL.

---

## 5. Deployment Architecture

AutoWeave is primarily a library, but the recommended local deployment stack relies on Docker Compose.

See [DEPLOYMENT.md](DEPLOYMENT.md) for details on container orchestration and scaling.

---

## 6. Context Resolution Stack

Context is resolved through a fallback mechanism, ensuring the agent gets the freshest and most accurate information available without overflowing the context window.

\`\`\`mermaid
flowchart LR
    Q[Context query] --> W[Workspace]
    W -->|miss| P[Postgres]
    P -->|miss| V[pgvector]
    V -->|miss| A[Artifact Store]
    A -->|miss| G[Neo4j]
    G -->|miss| R[Redis]
    R -->|miss| M[Typed miss / escalate]
\`\`\`

            `,
            'DEPLOYMENT': `
# Deployment Guide

AutoWeave Library is designed to be embedded into applications, but it requires several backing services to operate reliably in a production or local development environment.

## Backing Services

To run AutoWeave, you must provision:
1. **PostgreSQL** (with pgvector extension) - Canonical state and vector search.
2. **Redis** - Celery broker, distributed locks, heartbeats.
3. **Neo4j** (Optional) - For complex graph queries and memory associations.
4. **Artifact Storage** - A filesystem volume, AWS S3, or GCS for binary artifacts.
5. **OpenHands Agent Server** - The remote worker execution environment.

## Docker Compose (Local & Testing)

For local development, we provide a \`docker-compose.yml\` file that provisions the entire stack.

\`\`\`bash
docker compose up -d
\`\`\`

This stack includes:
- \`redis:7.4-alpine\`
- \`artifact-store\` (Alpine container mapping \`./var/artifacts\` to \`/data\`)
- \`autoweave-runtime\` (The library CLI/runner)
- \`openhands-agent-server\`

## Production Deployment Considerations

When deploying AutoWeave to a production environment (e.g., Kubernetes), consider the following:

### 1. Worker Isolation (Sandboxing)
AutoWeave delegates execution to OpenHands. OpenHands must run in a secure, isolated sandbox environment (e.g., Docker-in-Docker or gVisor) because it executes AI-generated code. Do not run OpenHands as root on the host machine.

### 2. High Availability
- **PostgreSQL**: Deploy in a highly available configuration (e.g., AWS RDS Multi-AZ, Cloud SQL HA).
- **Redis**: Use Redis Sentinel or a managed service (e.g., AWS ElastiCache) for failover.
- **AutoWeave Orchestrator**: The library is stateless and can be scaled horizontally.

### 3. Scaling Celery Workers
Task attempts are queued via Celery. To increase throughput:
- Increase the number of Celery worker processes.
- Ensure the Redis broker has sufficient connection limits and memory.

### 4. Storage Scaling
- Artifacts should be stored in cloud object storage (S3/GCS) rather than a local disk volume to ensure they are accessible across all nodes. Update \`ARTIFACT_STORE_URL\` accordingly.

### 5. Secrets Management
- Do not hardcode credentials in \`.env\` files for production.
- Inject \`VERTEXAI_SERVICE_ACCOUNT_FILE\`, \`POSTGRES_URL\`, and other secrets via a secrets manager (e.g., HashiCorp Vault, AWS Secrets Manager, Kubernetes Secrets).

            `,
            'autoweave_diagrams_source': `
# AutoWeave Diagrams Source

Version: 2.0
Purpose: text-first diagrams for coding agents and PDF generation.

---

## 1. System context

\`\`\`text
Human / Main Product / CLI
  -> AutoWeave Orchestrator
     -> Config Compiler
     -> Context Service
     -> Artifact Registry
     -> Approval Service
     -> Event / Observability Service
     -> Postgres + pgvector
     -> Redis + Celery
     -> Neo4j
     -> OpenHands agent-server workers
        -> isolated sandbox/worktree per task attempt
        -> Vertex AI model calls through injected worker credentials
\`\`\`

\`\`\`mermaid
flowchart TD
    H[Human / Main Product / CLI] --> O[AutoWeave Orchestrator]
    O --> CC[Config Compiler]
    O --> CS[Context Service]
    O --> AR[Artifact Registry]
    O --> AP[Approval Service]
    O --> EV[Observability Service]
    O --> PG[(Postgres + pgvector)]
    O --> RD[(Redis)]
    O --> CY[Celery]
    O --> N4[(Neo4j)]
    O --> OH[OpenHands Remote Workers]
    OH --> SB[Isolated sandbox/worktree]
    OH --> VX[Vertex AI]
\`\`\`

---

## 2. Manager -> backend/frontend -> integration -> review

\`\`\`mermaid
flowchart LR
    H[Human task] --> M[Manager attempt]
    M --> G[Persist graph revision]
    G --> BC[backend_contract]
    G --> FU[frontend_ui]
    BC --> BI[backend_impl]
    BI --> IN[integration]
    FU --> IN
    IN --> RV[review]
    RV --> DONE[complete]
\`\`\`

---

## 3. Dynamic scheduling rules

\`\`\`text
If all hard dependencies complete and no approval/human gate blocks the task,
then the task becomes READY and the scheduler may fan it out immediately.
Only downstream chains of blocked tasks pause.
Unrelated branches continue.
\`\`\`

\`\`\`mermaid
flowchart TD
    A[Task A ready] --> RA[Run A]
    B[Task B ready] --> RB[Run B]
    RA --> C{Unlocks Task C?}
    RB --> D{Unlocks Task D?}
    C -->|yes| RC[Run C]
    D -->|blocked on human| WH[waiting_for_human]
    RC --> E[Continue unrelated branch]
\`\`\`

---

## 4. Artifact handoff

\`\`\`mermaid
flowchart LR
    PA[Producing agent] --> PUT[put_artifact]
    PUT --> REG[Artifact Registry]
    REG --> ORC[Orchestrator dependency + visibility resolver]
    ORC --> GET[get_upstream_artifacts]
    GET --> DA[Downstream agent]
\`\`\`

---

## 5. Human-in-the-loop

\`\`\`mermaid
flowchart TD
    AG[Worker attempt] --> Q[request_clarification / approval / blocker]
    Q --> OR[Orchestrator validates]
    OR --> HR[HumanRequest or ApprovalRequest]
    HR --> MG[Manager formats human-facing question]
    MG --> HU[Human answer]
    HU --> OR2[Orchestrator records answer]
    OR2 --> RS[Resume correct attempt or create retry]
\`\`\`

---

## 6. Context resolution stack

\`\`\`text
1. workspace/live files
2. Postgres structured records
3. pgvector semantic retrieval
4. artifact store
5. Neo4j traversal
6. Redis live state
7. typed miss / human escalation
\`\`\`

\`\`\`mermaid
flowchart LR
    Q[Context query] --> W[Workspace]
    W -->|miss| P[Postgres]
    P -->|miss| V[pgvector]
    V -->|miss| A[Artifact Store]
    A -->|miss| G[Neo4j]
    G -->|miss| R[Redis]
    R -->|miss| M[Typed miss / escalate]
\`\`\`

---

## 7. Observability export

\`\`\`mermaid
flowchart TD
    OH[OpenHands events + spans] --> WA[Worker Adapter]
    WA --> DE[Domain events]
    WA --> SP[OpenTelemetry spans]
    WA --> MT[Metrics]
    DE --> PG[(Postgres event log)]
    SP --> OT[OTLP backend]
    MT --> MB[Metrics backend]
    PG --> API[Query + live stream API]
    API --> MP[Main product timeline / audit]
\`\`\`

---

## 8. Core domain classes

\`\`\`mermaid
classDiagram
    class Project
    class Team
    class AgentDefinition
    class WorkflowDefinition
    class WorkflowRun
    class Task
    class TaskEdge
    class TaskAttempt
    class Artifact
    class Decision
    class MemoryEntry
    class HumanRequest
    class ApprovalRequest
    class Event
    class ModelRoute
    class WorkspaceRecord

    Project --> Team
    Project --> AgentDefinition
    Project --> WorkflowDefinition
    WorkflowDefinition --> WorkflowRun
    WorkflowRun --> Task
    Task --> TaskEdge
    Task --> TaskAttempt
    TaskAttempt --> Artifact
    TaskAttempt --> Decision
    WorkflowRun --> Event
    Task --> HumanRequest
    Task --> ApprovalRequest
    TaskAttempt --> ModelRoute
    TaskAttempt --> WorkspaceRecord
\`\`\`

---

## 9. Service classes

\`\`\`mermaid
classDiagram
    class OrchestratorService
    class WorkflowEngine
    class Scheduler
    class WorkerManager
    class ConfigCompiler
    class ContextService
    class ArtifactRegistry
    class ApprovalService
    class EventService
    class ModelRouter
    class GraphProjectionService
    class ObservabilityExporter
    class StorageUnitOfWork

    OrchestratorService --> WorkflowEngine
    OrchestratorService --> Scheduler
    OrchestratorService --> WorkerManager
    OrchestratorService --> ContextService
    OrchestratorService --> ArtifactRegistry
    OrchestratorService --> ApprovalService
    OrchestratorService --> EventService
    OrchestratorService --> ModelRouter
    OrchestratorService --> GraphProjectionService
    OrchestratorService --> ObservabilityExporter
    OrchestratorService --> StorageUnitOfWork
    WorkerManager --> ConfigCompiler
\`\`\`

---

## 10. Worker lifecycle

\`\`\`mermaid
sequenceDiagram
    participant O as Orchestrator
    participant DB as Postgres
    participant RD as Redis
    participant C as Compiler
    participant W as OpenHands Worker
    participant V as Vertex AI

    O->>DB: create task_attempt
    O->>RD: acquire lease + heartbeat
    O->>C: compile canonical config
    C-->>O: compiled OpenHands config
    O->>W: launch remote worker
    W->>V: model calls via injected credentials
    W-->>O: events, artifacts, summaries
    O->>DB: finalize attempt state
    O->>RD: release lease
\`\`\`

            `,
            'autoweave_high_level_architecture': `
# AutoWeave High-Level Architecture

Version: 2.0  
Status: frozen architecture baseline  
Primary runtime: **OpenHands agent-server remote workers**  
Primary model platform: **Google Vertex AI**  
Primary operator surface: **terminal-first application / library-first control plane**

---

## 1. Executive summary

AutoWeave is a **multi-agent orchestration and control-plane library**.

It is not a clone of OpenHands, and it is not a thin wrapper around OpenHands.

The system is split deliberately:

- **AutoWeave** owns orchestration, workflow state, task graphs, approvals, context and memory services, artifact routing, model routing, observability, auditability, and policy.
- **OpenHands** owns single-agent execution inside an isolated remote sandbox/workspace: tool use, file editing, command execution, local skill loading, and step-level agent behavior.

The key architecture decisions are:

1. **OpenHands runs through agent-server remote workers**. Embedded local mode may exist for developer convenience, but remote workers are the production architecture.
2. **AutoWeave owns the canonical schema**. AutoWeave compiles canonical agent/task/runtime state into OpenHands-facing run config.
3. **Vertex AI is the primary model platform**. Credentials are injected into workers by the AutoWeave runtime; agents do not log in interactively.
4. **PostgreSQL is the source of truth** for durable state.
5. **Redis + Celery** provide ephemeral coordination, queues, leases, heartbeats, and background execution.
6. **Neo4j is included** for both relationship traversal and graph-oriented retrieval, but it is still downstream of canonical truth.
7. **Agents retrieve context through tools/services**, not by receiving giant prepacked prompts.
8. **One sandbox/worktree per task attempt** is the default.
9. **Dynamic parallelism is orchestrator-controlled**. Independent branches fan out automatically when dependencies and policy allow.
10. **Observability is exported through AutoWeave-normalized events, spans, and metrics**, not by exposing raw OpenHands internals directly to the main product.

---

## 2. Product goals

### Goals

1. Orchestrate specialized agents as one coherent engineering team.
2. Keep durable system truth outside worker-local state.
3. Support dynamic task decomposition, dependency-aware scheduling, human clarification, approvals, retries, and resumability.
4. Provide precise context retrieval and memory layers without uncontrolled prompt bloat.
5. Preserve full provenance: which agent did what, when, with which inputs, outputs, and approvals.
6. Expose clean telemetry and history to a future main product.
7. Start coding-first while remaining extensible to non-coding workflows later.

### Non-goals

1. Rebuild OpenHands' internal reasoning and tool loop.
2. Use a shared mutable workspace for all agents.
3. Give agents raw SQL or raw graph query access.
4. Depend on worker-local file persistence as the distributed source of truth.
5. Make peer-to-peer free-form chat the main coordination mechanism.
6. Build the product UI in phase one.

---

## 3. Architecture principles

1. **Single orchestrator rule**  
   AutoWeave is the only workflow authority.

2. **Workers are execution engines, not workflow engines**  
   OpenHands executes one task attempt at a time; it does not own the team DAG.

3. **Structured handoff beats free chat**  
   Agents coordinate mainly through tasks, artifacts, decisions, approvals, and events.

4. **Source-of-truth discipline**  
   Postgres is canonical. Redis is ephemeral. Celery executes. Neo4j projects and answers graph-heavy queries. Sandboxes hold working copies.

5. **Context is layered and scoped**  
   Agent identity context, live run context, durable scoped memory, and shared project memory are distinct.

6. **Human intervention is first-class**  
   Clarifications, approvals, and overrides are formal workflow objects.

7. **Compilation over duplication**  
   AutoWeave stores canonical config and compiles worker-facing OpenHands config just in time.

8. **Observability is productized**  
   The library emits domain events, spans, metrics, and replay artifacts that the main product can consume directly.

---

## 4. System layers

### 4.1 Control plane

- CLI / terminal application
- orchestrator service
- workflow compiler and scheduler
- agent registry and config compiler
- model router
- context and memory service
- artifact registry
- approval and clarification service
- event and audit service
- observability exporter
- graph projection service

### 4.2 Worker plane

- OpenHands agent-server remote workers
- one remote sandbox/worktree per task attempt
- compiled OpenHands run config per attempt
- worker-local tool use, bash, file edits, and local workspace reads
- worker access to AutoWeave MCP/context tools

### 4.3 Storage plane

- PostgreSQL + pgvector
- Redis
- Celery
- Neo4j
- object/blob storage for heavy artifacts and logs
- Git worktrees and sandbox-local filesystems

### 4.4 Observability plane

- normalized domain events persisted by AutoWeave
- OpenTelemetry spans and correlations
- metrics aggregation
- live stream API (SSE/WebSocket)
- query API for history/audit
- replay/debug artifacts for deep inspection

---

## 5. Responsibility boundary

### AutoWeave owns

- workflow definitions and workflow runs
- task graph creation, mutation, and evaluation
- human approval and clarification lifecycles
- canonical task and attempt state
- memory namespaces, retrieval policy, writeback policy, compaction policy
- artifact registry and visibility policy
- Vertex AI model-routing policy
- dispatch, retries, fan-out, and resume logic
- audit history and observability export
- graph projection into Neo4j
- policy and secret distribution to workers

### OpenHands owns

- one attempt's reasoning/action loop
- worker-local tool execution
- file edits in the attempt workspace
- command execution in the attempt sandbox
- local skill loading and prompt shaping after AutoWeave compilation
- worker-local confirmation/step-level safety behavior

---

## 6. Canonical data-flow

\`\`\`text
Human / CLI
  -> AutoWeave Orchestrator
     -> Postgres (truth)
     -> Redis (leases, queues, heartbeats)
     -> Celery (dispatch/background jobs)
     -> Neo4j (graph projection + graph retrieval)
     -> Artifact Store
     -> OpenHands Remote Worker
         -> Sandbox / Worktree / Repo Copy
         -> AutoWeave Context + Artifact + Approval tools
  -> AutoWeave Event / Trace / Metric export
  -> Main product / dashboards / replay
\`\`\`

---

## 7. Workflow model and dynamic parallelism

AutoWeave executes a **task DAG**, not a linear queue.

Each task has:
- assigned role
- state
- hard and soft dependency edges
- expected artifact outputs
- optional approval requirements
- optional human-interaction rules
- model-routing hints
- memory scopes

A task is runnable when:
- state is \`ready\`
- all hard dependencies are satisfied
- required approvals are present
- required human blockers are cleared
- a worker lease can be acquired

### Dynamic parallelism

Dynamic parallelism means:
- the orchestrator reevaluates the runnable set after every material event
- any independent tasks become runnable immediately
- only downstream chains of blocked tasks pause
- unrelated branches continue

### Example

Request: **“Build notifications settings page with backend API support.”**

Manager proposes:
- \`backend_contract\`
- \`backend_impl\`
- \`frontend_ui\`
- \`integration\`
- \`review\`

Dependencies:
- \`backend_impl\` depends on \`backend_contract\`
- \`integration\` depends on \`backend_impl\` and \`frontend_ui\`
- \`review\` depends on \`integration\`

Runtime behavior:
- \`backend_contract\` and \`frontend_ui\` may start in parallel
- when \`backend_contract\` completes, \`backend_impl\` becomes runnable
- when \`backend_impl\` and \`frontend_ui\` complete, \`integration\` becomes runnable
- if \`integration\` blocks on human clarification, only \`integration -> review\` pauses
- unrelated branches would continue

---

## 8. Cross-agent coordination and artifact handoff

Agents do **not** pass files peer-to-peer as the primary mechanism.

The model is:

\`\`\`text
Producing agent
  -> put_artifact / record_decision
  -> AutoWeave artifact registry + decision log
  -> orchestrator attaches eligible upstream outputs to dependent tasks
  -> downstream agent retrieves through tools
\`\`\`

### Coordination objects

- tasks
- task dependencies
- artifacts
- decisions
- approvals
- human requests
- state transitions
- reviewer feedback

### Default artifact visibility

A task can see:
- its own task inputs
- explicitly attached artifacts
- eligible upstream artifacts from dependency-linked tasks
- role-allowed shared/project artifacts

A task cannot automatically see:
- artifacts from unrelated workflows
- sensitive artifacts outside its policy scope
- draft artifacts unless the workflow explicitly allows draft consumption

### Artifact lifecycle

- \`draft\`
- \`final\`
- \`superseded\`
- \`archived\`

---

## 9. Human-in-the-loop model

Workers do not directly mutate canonical workflow state.

A worker may request:
- clarification
- approval
- state transition
- escalation
- blocker reporting

AutoWeave validates and persists the real transition.

### Human loop flow

1. worker reports a blocker or clarification need
2. orchestrator records \`human_request\`
3. task moves to \`waiting_for_human\` or \`waiting_for_approval\`
4. manager agent may rewrite the raw worker request into a cleaner human-facing question
5. human answers in terminal/main product
6. orchestrator stores answer, emits events, and resumes the correct task attempt or follow-up attempt

### Important boundary

The manager agent is the **human-facing conversational role**, but the orchestrator remains the **state authority**.

---

## 10. Context and memory model

AutoWeave uses layered context.

### 10.1 Agent identity context

Static per agent:
- role
- prompt/soul
- playbook
- tool permissions
- model profile hints
- sandbox profile
- memory scopes

### 10.2 Live run context

Ephemeral per attempt:
- current task brief
- recent tool outputs
- workspace status
- open blockers
- current upstream artifact bindings

### 10.3 Durable memory layers

#### Episodic memory
- workflow runs
- task attempts
- human interactions
- failures
- retries

#### Semantic memory
- facts
- summaries
- decisions
- extracted constraints

#### Procedural memory
- playbooks
- agent policies
- reusable operational rules

#### Code memory
- indexed files/chunks
- summaries
- diffs
- prior fixes
- module history

#### Graph memory
- relationships across tasks, artifacts, files, modules, decisions, agents, and runs

### Retrieval order

When context is requested, the context service resolves in this order:
1. active workspace / local attempt files
2. Postgres structured truth
3. pgvector semantic retrieval
4. artifact/blob store
5. Neo4j relationship traversal
6. Redis live ephemeral state
7. human escalation if still unresolved

### Missing-context policy

Missing context is a first-class result, not a silent failure.

Typed outcomes:
- \`not_found\`
- \`not_indexed_yet\`
- \`waiting_for_dependency\`
- \`access_denied\`
- \`needs_human_input\`

---

## 11. Vertex AI model platform

AutoWeave standardizes on **Vertex AI** for production model execution.

### Credential model

- no interactive login inside workers
- production credentials come from the main product / secret manager
- AutoWeave injects the worker environment expected by OpenHands
- local development may use a local secrets file that the runtime converts into worker env

### Canonical runtime secrets

At the AutoWeave layer, use these canonical settings:
- \`VERTEXAI_PROJECT\`
- \`VERTEXAI_LOCATION\`
- \`VERTEXAI_SERVICE_ACCOUNT_FILE\` (local dev) or secret-manager equivalent

At worker compile/injection time, materialize the OpenHands-side env expected by the worker runtime:
- \`GOOGLE_APPLICATION_CREDENTIALS\`
- \`VERTEXAI_PROJECT\`
- \`VERTEXAI_LOCATION\`

### Routing policy

Routing can vary by:
- agent role
- task type
- complexity
- latency target
- cost budget
- reliability/risk level
- retry history

Examples:
- manager/planner -> stronger reasoning profile
- complex backend integration -> stronger coding profile
- boilerplate or low-risk refactor -> cheaper profile
- repeated failure -> escalate route automatically

---

## 12. Sandboxes and workspaces

Default policy:
- one sandbox/worktree per task attempt
- reuse only when resuming the same attempt
- no shared mutable worktree as default

### Why

This prevents:
- file collisions
- hidden contamination between agents
- polluted dependency state
- weak reproducibility
- ambiguous provenance

### Shared elements that are allowed

- same origin repository
- same base container image
- shared package/dependency cache
- shared artifact store
- shared durable memory stores

---

## 13. Observability and export to the main product

The library must export observability in a way the main product can consume without understanding OpenHands internals.

### 13.1 Three observability outputs

#### A. Domain events
Product-facing, normalized, persisted by AutoWeave.

Examples:
- \`workflow.created\`
- \`task.ready\`
- \`task.blocked\`
- \`attempt.started\`
- \`artifact.published\`
- \`human_request.opened\`
- \`approval.requested\`
- \`route.selected\`
- \`sandbox.orphaned\`

#### B. OpenTelemetry spans
Engineering-facing.

Examples:
- workflow compile
- DAG mutation
- task dispatch
- worker start
- context retrieval
- artifact upload
- approval wait
- retry
- Neo4j projection update
- sandbox cleanup

#### C. Metrics
Examples:
- queue latency
- attempt duration
- approval wait time
- retry count
- model-route cost
- blocked-time by reason
- artifact volume
- failure rate by provider/profile

### 13.2 Export model

\`\`\`text
OpenHands worker events + spans
  -> AutoWeave worker adapter
  -> normalized domain events + correlated spans + metrics
  -> Postgres event log + OTLP exporter + live stream
  -> Main product timeline / dashboards / traces / replay
\`\`\`

### 13.3 Main product integration

The main product should consume:
- **live stream API** for in-progress runs
- **query API** for history and audit
- **trace backend / OTLP sink** for deep debugging
- **artifact URLs/handles** for drill-down

### Required correlation fields

Every event/span should carry:
- \`workflow_run_id\`
- \`task_id\`
- \`task_attempt_id\`
- \`agent_id\`
- \`agent_role\`
- \`sandbox_id\`
- \`provider_name\`
- \`model_name\`
- \`route_reason\`
- \`event_type\`
- \`source\`
- \`sequence_no\`
- \`created_at\`

---

## 14. Edge cases and required resolutions

### Workflow / scheduling
- cycle in the task graph -> reject at compile time and on dynamic mutation
- duplicate dispatch -> idempotency keys + DB uniqueness + Redis lease
- blocked branch freezing unrelated work -> only block downstream dependents
- stale upstream artifact version -> bind artifact versions and mark stale consumers

### Human loop
- late human answer after retry/completion -> attach as artifact/comment, do not auto-resume wrong attempt
- multiple raw questions from one task -> consolidate into one human request
- human answer conflicts with prior decision -> require supersede event

### Context / memory
- context missing in Postgres -> fallback layered search, typed miss result
- indexing lag -> return \`not_indexed_yet\`, retry or read directly from workspace
- noisy writeback -> only durable-write structured artifacts, decisions, blockers, summaries
- compaction losing detail -> store structured compaction output plus raw artifacts/logs

### Workspaces
- sandbox loss mid-run -> attempt remains canonical in Postgres; retry with fresh sandbox and structured resume inputs
- shared worktree collisions -> prevented by one-worktree-per-attempt default
- stale code index vs live workspace -> prefer live workspace for active attempt

### Vertex / routing
- provider outage -> fallback route by policy, log route degradation
- repeated cheap-model failure -> escalate automatically
- route change across retries -> rely on structured summaries and artifact refs rather than raw session continuity

### Graph
- Neo4j and Postgres drift -> Postgres remains canonical; graph updated asynchronously from outbox/events
- graph explosion -> tier graph projection, archive low-value edges, keep critical provenance edges

### Observability
- telemetry backend outage -> main product still reads from AutoWeave event log
- out-of-order worker events -> logical sequence numbers per attempt
- secrets in traces/logs -> redact before persistence/export

---

## 15. Recommended repository layout

\`\`\`text
autoweave/
  apps/
    cli/
  autoweave/
    approvals/
    artifacts/
    compiler/
    context/
    events/
    graph/
    memory/
    observability/
    orchestration/
    routing/
    storage/
    workers/
    workflows/
  agents/
    manager/
    backend/
    frontend/
    reviewer/
  configs/
    runtime/
    workflows/
    routing/
  docs/
  tests/
  .env.example
  AGENTS.md
\`\`\`

---

## 16. Text diagrams

### 16.1 End-to-end control flow

\`\`\`mermaid
flowchart TD
    H[Human / CLI] --> ORCH[AutoWeave Orchestrator]
    ORCH --> PG[(Postgres + pgvector)]
    ORCH --> RD[(Redis)]
    ORCH --> CY[Celery]
    ORCH --> N4[(Neo4j)]
    ORCH --> AR[Artifact Store]
    ORCH --> CMP[Config Compiler]
    CMP --> OW[OpenHands Remote Worker]
    OW --> SB[Sandbox + Worktree]
    OW --> CTS[Context / Artifact / Approval tools]
    OW --> EV[Worker events]
    EV --> OBS[AutoWeave Observability Export]
    OBS --> MP[Main Product / Timeline / Traces]
\`\`\`

### 16.2 Dynamic DAG scheduling

\`\`\`mermaid
flowchart LR
    M[Manager planning task] --> G[Persist DAG]
    G --> A[backend_contract READY]
    G --> B[frontend_ui READY]
    A --> C[backend_impl READY]
    B --> D[integration waits on backend_impl]
    C --> D[integration READY]
    D --> E[review READY]
\`\`\`

### 16.3 Human-in-the-loop

\`\`\`mermaid
flowchart TD
    AG[Worker attempt] -->|request_clarification| OR[Orchestrator]
    OR --> HR[Human request opened]
    HR --> MG[Manager formats question]
    MG --> HU[Human answers]
    HU --> OR
    OR --> RS[Resume correct task attempt]
\`\`\`

### 16.4 Artifact handoff

\`\`\`mermaid
flowchart LR
    BA[Backend agent] -->|put_artifact api_contract| REG[Artifact Registry]
    REG --> ORC[Orchestrator dependency resolver]
    ORC --> FE[Frontend/integration task sees eligible upstream artifact]
    FE -->|get_upstream_artifacts| REG
\`\`\`

### 16.5 Observability export

\`\`\`mermaid
flowchart LR
    OH[OpenHands worker] --> WA[Worker adapter]
    WA --> DE[Domain events]
    WA --> SP[OTEL spans]
    WA --> MT[Metrics]
    DE --> PG[(Postgres event log)]
    SP --> OTLP[OTLP exporter]
    MT --> MET[Metrics backend]
    PG --> API[Live stream + query API]
    API --> MP[Main product]
\`\`\`

---

## 17. Final architecture conclusion

AutoWeave should be implemented as a **Vertex-AI-backed multi-agent control plane** on top of **OpenHands remote workers**, with **Postgres as truth**, **Redis/Celery as coordination**, **Neo4j as graph retrieval/projection**, **isolated worktrees per attempt**, **dynamic DAG scheduling**, and **normalized observability export** for the main product.

            `,
            'autoweave_implementation_spec': `
# AutoWeave Implementation Specification

Version: 2.0  
Status: implementation baseline  
Primary runtime: **OpenHands agent-server remote workers**  
Primary model platform: **Google Vertex AI**  
Canonical schema: **AutoWeave-owned; compiled into OpenHands config**

---

## 1. Scope

This document defines the implementation contract for:
- canonical config schema
- orchestrator behavior
- storage schema
- dynamic DAG scheduling
- human-in-the-loop
- context/memory services
- artifact routing
- Vertex AI model routing
- OpenHands worker adapter
- Neo4j projection and retrieval
- observability export
- testing and edge-case coverage

The terminal application and library code are in scope. A graphical product UI is out of scope.

---

## 2. Implementation priorities

### Mandatory
1. Canonical AutoWeave schema and compiler
2. Orchestrator + task DAG engine
3. Postgres source-of-truth repositories
4. Redis leases/heartbeats
5. Remote OpenHands worker adapter
6. Vertex AI routing and credential injection
7. Artifact registry and visibility resolver
8. Human request / approval subsystem
9. Neo4j graph projection + graph lookup interfaces
10. Observability event/trace/metric export
11. Full test harness

### Explicitly deferred
1. GUI product surface
2. public plugin marketplace
3. alternate worker runtimes beyond OpenHands
4. external skill marketplace

---

## 3. Canonical repository and config contract

\`\`\`text
agents/
  manager/
    soul.md
    playbook.yaml
    autoweave.yaml
    skills/
  backend/
    soul.md
    playbook.yaml
    autoweave.yaml
    skills/
  frontend/
    soul.md
    playbook.yaml
    autoweave.yaml
    skills/
  reviewer/
    soul.md
    playbook.yaml
    autoweave.yaml
    skills/

configs/
  workflows/
    team.workflow.yaml
  routing/
    model_profiles.yaml
  runtime/
    runtime.yaml
    storage.yaml
    vertex.yaml
    observability.yaml

config/
  secrets/
    vertex_service_account.json   # gitignored in local dev

.env.example
.env.local                        # gitignored in local dev
AGENTS.md
context.md
implementation_plan.md
task_list.md
\`\`\`

### 3.1 Canonical agent files

#### \`soul.md\`
Agent identity and behavioral guidance.

#### \`playbook.yaml\`
Machine-readable local operating procedure.

#### \`autoweave.yaml\`
AutoWeave-owned agent metadata.

Required fields:
- \`name\`
- \`role\`
- \`description\`
- \`allowed_workflow_stages\`
- \`default_memory_scopes\`
- \`allowed_tool_groups\`
- \`sandbox_profile\`
- \`model_profile_hints\`
- \`approval_policy\`
- \`human_interaction_policy\`
- \`artifact_contracts\`
- \`route_priority\`

### 3.2 Workflow definition

\`configs/workflows/team.workflow.yaml\`

Required top-level fields:
- \`name\`
- \`version\`
- \`roles\`
- \`stages\`
- \`entrypoint\`
- \`policies\`
- \`task_templates\`
- \`completion_rules\`

Task template fields:
- \`key\`
- \`title\`
- \`assigned_role\`
- \`description_template\`
- \`hard_dependencies\`
- \`soft_dependencies\`
- \`required_artifacts\`
- \`produced_artifacts\`
- \`approval_requirements\`
- \`memory_scopes\`
- \`route_hints\`

### 3.3 Runtime config

#### \`runtime.yaml\`

- default concurrency
- retry policy
- heartbeat intervals
- cleanup schedules
- compaction thresholds

#### \`storage.yaml\`
- Postgres DSN name
- Redis DSN name
- Neo4j DSN name
- artifact store config
- pgvector index config

#### \`vertex.yaml\`
- provider name: \`VertexAI\`
- profile definitions
- fallback order
- timeout policy
- retry policy
- token/cost budgets

#### \`observability.yaml\`
- event retention policy
- OTLP exporter config
- metric sinks
- redaction rules
- replay retention windows

---

## 4. Credential model for Vertex AI

### 4.1 Local development contract

Local developers place the GCP service-account JSON at:
- \`config/secrets/vertex_service_account.json\`

Local ignored environment file:

\`\`\`env
VERTEXAI_PROJECT=
VERTEXAI_LOCATION=
VERTEXAI_SERVICE_ACCOUNT_FILE=./config/secrets/vertex_service_account.json
POSTGRES_URL=
REDIS_URL=
NEO4J_URL=
NEO4J_USERNAME=
NEO4J_PASSWORD=
ARTIFACT_STORE_URL=
\`\`\`

### 4.2 Runtime injection contract

The worker adapter converts local/secret-manager config into the OpenHands-side environment expected by the worker runtime:
- \`GOOGLE_APPLICATION_CREDENTIALS\`
- \`VERTEXAI_PROJECT\`
- \`VERTEXAI_LOCATION\`

Implementation note:
- support secret-manager-native injection in production
- support local file-based materialization in dev
- never require interactive login inside workers

### 4.3 Provider selection

OpenHands provider config for production attempts must resolve to:
- \`LLM Provider = VertexAI\`
- \`LLM Model = vertex_ai/<model-name>\` or equivalent compiled model string

---

## 5. Core domain model

### 5.1 Primary entities

#### Project
Fields:
- \`id\`
- \`slug\`
- \`name\`
- \`repo_url\`
- \`default_branch\`
- \`settings_json\`
- \`created_at\`
- \`updated_at\`

#### Team
Fields:
- \`id\`
- \`project_id\`
- \`name\`
- \`workflow_definition_id\`
- \`status\`
- \`created_at\`
- \`updated_at\`

#### AgentDefinition
Fields:
- \`id\`
- \`project_id\`
- \`role\`
- \`name\`
- \`version\`
- \`soul_md\`
- \`playbook_yaml\`
- \`autoweave_yaml\`
- \`status\`
- \`created_at\`
- \`updated_at\`

#### WorkflowDefinition
Fields:
- \`id\`
- \`project_id\`
- \`version\`
- \`content_yaml\`
- \`checksum\`
- \`status\`
- \`created_at\`

#### WorkflowRun
Fields:
- \`id\`
- \`project_id\`
- \`team_id\`
- \`workflow_definition_id\`
- \`graph_revision\`
- \`root_input_json\`
- \`status\`
- \`started_at\`
- \`ended_at\`

#### Task
Fields:
- \`id\`
- \`workflow_run_id\`
- \`task_key\`
- \`title\`
- \`description\`
- \`assigned_role\`
- \`state\`
- \`priority\`
- \`input_json\`
- \`output_json\`
- \`required_artifact_types_json\`
- \`produced_artifact_types_json\`
- \`created_at\`
- \`updated_at\`

#### TaskEdge
Fields:
- \`id\`
- \`workflow_run_id\`
- \`from_task_id\`
- \`to_task_id\`
- \`edge_type\`
- \`is_hard_dependency\`
- \`created_at\`

#### TaskAttempt
Fields:
- \`id\`
- \`task_id\`
- \`attempt_number\`
- \`state\`
- \`worker_mode\`
- \`agent_definition_id\`
- \`workspace_id\`
- \`compiled_worker_config_json\`
- \`model_route_id\`
- \`lease_key\`
- \`started_at\`
- \`ended_at\`

#### Artifact
Fields:
- \`id\`
- \`workflow_run_id\`
- \`task_id\`
- \`task_attempt_id\`
- \`produced_by_role\`
- \`artifact_type\`
- \`title\`
- \`summary\`
- \`status\`
- \`version\`
- \`storage_uri\`
- \`checksum\`
- \`metadata_json\`
- \`created_at\`

#### Decision
Fields:
- \`id\`
- \`workflow_run_id\`
- \`task_id\`
- \`task_attempt_id\`
- \`title\`
- \`decision_text\`
- \`rationale\`
- \`status\`
- \`created_at\`

#### MemoryEntry
Fields:
- \`id\`
- \`project_id\`
- \`scope_type\`
- \`scope_id\`
- \`memory_layer\`
- \`content\`
- \`metadata_json\`
- \`valid_from\`
- \`valid_to\`
- \`created_at\`

#### HumanRequest
Fields:
- \`id\`
- \`workflow_run_id\`
- \`task_id\`
- \`task_attempt_id\`
- \`request_type\`
- \`question\`
- \`context_summary\`
- \`status\`
- \`answer_text\`
- \`answered_by\`
- \`answered_at\`
- \`created_at\`

#### ApprovalRequest
Fields:
- \`id\`
- \`workflow_run_id\`
- \`task_id\`
- \`task_attempt_id\`
- \`approval_type\`
- \`reason\`
- \`status\`
- \`resolved_by\`
- \`resolved_at\`
- \`created_at\`

#### Event
Fields:
- \`id\`
- \`workflow_run_id\`
- \`task_id\`
- \`task_attempt_id\`
- \`event_type\`
- \`source\`
- \`sequence_no\`
- \`payload_json\`
- \`created_at\`

#### ModelRoute
Fields:
- \`id\`
- \`workflow_run_id\`
- \`task_id\`
- \`task_attempt_id\`
- \`provider_name\`
- \`model_name\`
- \`route_reason\`
- \`fallback_from\`
- \`estimated_cost_class\`
- \`created_at\`

#### WorkspaceRecord
Fields:
- \`id\`
- \`workflow_run_id\`
- \`task_attempt_id\`
- \`sandbox_id\`
- \`repo_ref\`
- \`branch_name\`
- \`worktree_path_or_uri\`
- \`status\`
- \`created_at\`
- \`ended_at\`

---

## 6. Task and attempt state machines

### 6.1 Task states
- \`created\`
- \`ready\`
- \`in_progress\`
- \`waiting_for_dependency\`
- \`waiting_for_human\`
- \`waiting_for_approval\`
- \`blocked\`
- \`completed\`
- \`failed\`
- \`cancelled\`

### 6.2 Attempt states
- \`queued\`
- \`dispatching\`
- \`running\`
- \`paused\`
- \`needs_input\`
- \`succeeded\`
- \`errored\`
- \`aborted\`
- \`orphaned\`

### 6.3 Transition rules

- only the orchestrator may change canonical task state
- workers may request, not force, state changes
- a task cannot reach \`completed\` while unresolved hard dependencies remain
- retries create a new attempt record; old attempts remain immutable

---

## 7. Dynamic DAG scheduler

### 7.1 Readiness rules

A task is runnable when:
1. task state is \`ready\`
2. all hard upstream dependencies are \`completed\`
3. no unresolved approval/human gate blocks the task
4. concurrency policy allows another lease
5. required artifact contracts from upstream tasks are satisfied

### 7.2 Scheduler loop

1. listen to material events
2. acquire scheduler lock
3. load affected workflow run and graph revision
4. recompute readiness for impacted tasks
5. enqueue runnable tasks that have no active running attempt
6. release lock

### 7.3 Dynamic mutation

The orchestrator may mutate the graph at runtime only by creating a new \`graph_revision\` and persisting graph-change events.

Rules:
- detect cycles on every mutation
- reevaluate only affected subgraph where possible
- if a dependency is added to a currently running task, mark the task \`blocked_by_graph_change\` and apply policy

### 7.4 Concurrency policy

Implement:
- global max active attempts
- per-workflow max active attempts
- per-role max active attempts
- per-project max active attempts
- queue priority with starvation prevention

---

## 8. Human-in-the-loop subsystem

### 8.1 Worker request tools
- \`request_clarification\`
- \`request_approval\`
- \`report_blocker\`
- \`request_state_transition\`

### 8.2 Orchestrator behavior

On \`request_clarification\`:
- create \`HumanRequest\`
- move task to \`waiting_for_human\`
- emit \`human_request.opened\`
- optionally route through manager agent for rewriting

On human answer:
- persist answer
- emit \`human_request.answered\`
- transition task back to \`ready\` or resume policy target
- enqueue resume/retry flow

### 8.3 Important rules

- late answers do not auto-resume a completed task
- multiple open questions for the same task are consolidated where possible
- the manager is the human-facing summarizer, not the state authority

---

## 9. Context and memory service

### 9.1 Read tools
- \`get_task()\`
- \`get_upstream_artifacts(type?, from_role?)\`
- \`get_artifact(artifact_id)\`
- \`search_memory(query, scope, top_k)\`
- \`get_related_code_context(query, file_filters?)\`
- \`get_decisions(scope, tags?)\`

### 9.2 Write tools
- \`put_artifact(...)\`
- \`record_decision(...)\`
- \`append_attempt_note(...)\`
- \`request_clarification(...)\`
- \`request_approval(...)\`
- \`report_blocker(...)\`

### 9.3 Resolution order
1. workspace/live files
2. Postgres structured records
3. pgvector semantic search
4. artifact store
5. Neo4j traversal
6. Redis live state
7. typed miss / escalation

### 9.4 Typed miss response

\`\`\`json
{
  "found": false,
  "reason": "not_found | not_indexed_yet | waiting_for_dependency | access_denied | needs_human_input",
  "searched_sources": ["workspace", "postgres", "pgvector", "artifact_store", "neo4j", "redis"],
  "next_action": "continue_with_assumption | retry_later | wait_for_dependency | ask_human"
}
\`\`\`

### 9.5 Writeback policy

Persist durably when the output is:
- a decision
- an artifact needed later
- a blocker
- an approval request
- an end-of-step summary
- a human interaction summary

### 9.6 Compaction policy

Compaction is system-driven with optional agent-triggered requests.

Trigger on:
- context-budget threshold
- major step boundary
- before pause
- before handoff
- before retry
- after heavy/noisy tool bursts

---

## 10. Artifact registry and handoff contract

### 10.1 Artifact API

#### \`put_artifact\`
Request:
- \`task_attempt_id\`
- \`artifact_type\`
- \`title\`
- \`summary\`
- \`status\`
- \`payload_handle\`
- \`metadata\`

Response:
- \`artifact_id\`
- \`version\`
- \`storage_uri\`

#### \`get_upstream_artifacts\`
No raw task-id invention by the worker. The runtime already knows the current task attempt.

Request:
- optional \`type\`
- optional \`from_role\`
- optional \`status\`

Response:
- eligible artifacts from orchestrator-defined upstream scope

### 10.2 Visibility rules

Visibility is orchestrator-defined from:
- DAG dependencies
- artifact status
- workflow policy
- role policy
- sensitivity policy

Workers do not define their own upstream dependency graph.

### 10.3 Artifact status rules
- default downstream visibility: \`final\`
- \`draft\` visibility only when workflow explicitly allows it
- \`superseded\` artifacts remain historical but are not returned by default

---

## 11. OpenHands worker adapter

### 11.1 Adapter responsibilities
- compile canonical config into OpenHands-facing config
- provision remote workspace/sandbox
- inject Vertex AI runtime env
- attach allowed tools and MCP endpoints
- stream worker events
- collect outputs
- close/cleanup or archive workspace

### 11.2 Worker launch sequence

1. reserve task attempt lease
2. route model profile
3. compile config
4. provision remote sandbox/worktree
5. materialize Vertex credentials in worker env
6. start OpenHands agent-server run
7. stream events
8. handle completion/failure
9. persist artifacts/summaries/events
10. release lease and schedule next actions

### 11.3 Canonical config compiler

Compile from:
- \`soul.md\`
- \`playbook.yaml\`
- \`autoweave.yaml\`
- task input / workflow context
- runtime policy
- model route
- sandbox profile
- tool scopes

Into OpenHands-facing config fields:
- system prompt content
- tools/tool groups
- MCP servers
- permission mode
- provider/model
- hooks
- execution limits

---

## 12. Workspaces and sandboxes

### 12.1 Default policy
- one sandbox per task attempt
- one repo worktree per task attempt
- reuse only for resume of the same attempt

### 12.2 Resume policy

Resume can:
- reuse the same workspace if still healthy and lease-valid
- or create a fresh workspace and replay structured context/artifact bindings

### 12.3 Cleanup policy

- end successful attempts -> archive metadata and optional debug bundle
- orphaned attempts -> sweep after heartbeat TTL and reconciliation check
- failed cleanup -> create \`sandbox.cleanup_failed\` event and queue retry

---

## 13. Storage implementation

### 13.1 PostgreSQL

Canonical tables:
- \`projects\`
- \`teams\`
- \`agent_definitions\`
- \`workflow_definitions\`
- \`workflow_runs\`
- \`tasks\`
- \`task_edges\`
- \`task_attempts\`
- \`artifacts\`
- \`artifact_versions\`
- \`decisions\`
- \`memory_entries\`
- \`human_requests\`
- \`approval_requests\`
- \`events\`
- \`model_routes\`
- \`workspace_records\`
- \`documents\`
- \`document_chunks\`
- \`file_index\`
- \`file_chunks\`

### 13.2 Redis

Use for:
- active leases
- worker heartbeats
- queue coordination
- idempotency windows
- live stream cursors
- ephemeral progress snapshots

Suggested key patterns:
- \`lease:attempt:{attempt_id}\`
- \`heartbeat:attempt:{attempt_id}\`
- \`dispatch:workflow:{workflow_run_id}\`
- \`stream:workflow:{workflow_run_id}\`
- \`idempotency:{action_key}\`

### 13.3 Celery

Queues:
- \`dispatch\`
- \`workers\`
- \`indexing\`
- \`graph\`
- \`observability\`
- \`cleanup\`

Use for:
- task dispatch
- worker launch orchestration
- graph projection jobs
- index refresh jobs
- cleanup/sweeper jobs
- summary/compaction jobs

### 13.4 Neo4j

Use as graph projection and graph-retrieval store.

Primary node labels:
- \`WorkflowRun\`
- \`Task\`
- \`TaskAttempt\`
- \`Artifact\`
- \`Decision\`
- \`Agent\`
- \`File\`
- \`Module\`
- \`HumanRequest\`

Primary relationships:
- \`DEPENDS_ON\`
- \`PRODUCED\`
- \`USES\`
- \`AFFECTS\`
- \`REQUESTED\`
- \`ANSWERED\`
- \`REVIEWS\`
- \`SUPERSEDES\`

Rules:
- update from outbox/events asynchronously
- never treat Neo4j as canonical task-state truth
- graph queries may inform context retrieval, provenance, and impact analysis

---

## 14. Model routing on Vertex AI

### 14.1 Inputs to routing
- role
- task type
- estimated complexity
- budget class
- latency class
- reliability/risk class
- retry count
- workflow stage

### 14.2 Routing outcomes
- provider: always \`VertexAI\`
- model/profile
- timeout budget
- retry policy
- escalation target

### 14.3 Escalation ladder

Example:
- low-cost profile for boilerplate tasks
- balanced profile for ordinary implementation
- high-reasoning profile for manager, reviewer, integration, and repeated failures

### 14.4 Route auditability

Every route decision must create a \`ModelRoute\` record and a \`route.selected\` event.

---

## 15. Observability implementation

### 15.1 Event categories
- workflow events
- task events
- attempt events
- worker events
- artifact events
- approval/human events
- graph-projection events
- routing events
- sandbox events

### 15.2 Canonical event schema

Required fields:
- \`event_id\`
- \`workflow_run_id\`
- \`task_id\`
- \`task_attempt_id\`
- \`agent_id\`
- \`agent_role\`
- \`sandbox_id\`
- \`provider_name\`
- \`model_name\`
- \`route_reason\`
- \`event_type\`
- \`source\`
- \`severity\`
- \`sequence_no\`
- \`payload_json\`
- \`created_at\`

### 15.3 Span model

Emit spans for:
- \`workflow.compile\`
- \`workflow.schedule\`
- \`task.dispatch\`
- \`worker.launch\`
- \`context.fetch\`
- \`artifact.publish\`
- \`human_request.open\`
- \`approval.wait\`
- \`retry.schedule\`
- \`graph.project\`
- \`sandbox.cleanup\`

### 15.4 Export contract to the main product

The library must expose:
- live event stream API
- query API for timelines and attempt details
- OTLP export hooks
- metrics export hooks
- replay/debug artifact references

### 15.5 Redaction

Before persistence/export:
- classify payload fields as public/internal/secret
- redact secret-classified values
- never export raw service-account contents

---

## 16. Edge-case matrix and required behavior

### 16.1 Scheduler
1. DAG cycle -> reject compile/mutation
2. duplicate dispatch -> idempotent attempt launch
3. unrelated branches must continue when one branch blocks
4. downstream tasks unlock only after all hard deps complete
5. invalid worker-requested state transition -> reject and record event

### 16.2 Human loop
6. wrong routing of missing dependency as human input -> typed miss result prevents it
7. multiple clarifications for one task -> consolidate
8. late human answer -> attach but do not revive wrong attempt
9. approval rejection -> prevent completion and create follow-up route

### 16.3 Artifacts
10. artifact metadata without payload -> reconciliation job
11. payload without metadata -> orphan artifact sweep
12. draft artifact leakage -> visibility policy enforcement
13. huge artifact payload -> return handles or bounded payloads

### 16.4 Workspace/runtime
14. worker crash after artifact upload but before state write -> idempotent finalize logic + reconciliation
15. sandbox orphaned -> heartbeat TTL + sweeper
16. overlapping file changes in separate worktrees -> isolated by design
17. stale index vs live workspace -> current attempt prefers workspace reads

### 16.5 Storage/graph
18. Neo4j projection failure -> Postgres remains canonical; retry graph job
19. Redis loss -> reconstruct from Postgres events + active attempt records


### 16.6 Routing/provider
21. Vertex provider outage -> fallback profile and event
22. repeated cheaper-route failure -> escalation
23. route explainability -> route record required

### 16.7 Observability
24. telemetry backend outage -> product still reads Postgres event log
25. out-of-order worker events -> sequence numbers
26. secrets leak risk -> redaction pipeline
27. stream disconnect -> catch up from cursor using persisted events

---

## 17. Example workflow contract

### Example request
Build notifications settings page with backend API support.

### Example graph
- \`manager_plan\`
- \`backend_contract\`
- \`backend_impl\`
- \`frontend_ui\`
- \`integration\`
- \`review\`

Dependencies:
- \`backend_contract\` depends on \`manager_plan\`
- \`backend_impl\` depends on \`backend_contract\`
- \`frontend_ui\` depends on \`manager_plan\`
- \`integration\` depends on \`backend_impl\` and \`frontend_ui\`
- \`review\` depends on \`integration\`

### Expected runtime behavior
- manager plans and persists graph
- backend contract and frontend UI may run in parallel once ready
- backend implementation begins after contract finalization
- integration consumes upstream artifacts from backend + frontend
- integration may request human clarification
- review begins only after integration completion

---

## 18. Testing requirements

### 18.1 Unit tests
- config loaders and validators
- canonical-to-OpenHands compiler
- task state machine
- attempt state machine
- readiness evaluator
- route selection policy
- artifact visibility resolver
- missing-context resolver
- human request lifecycle
- approval lifecycle
- event correlation helpers
- graph projection mapper

### 18.2 Integration tests
- Postgres repositories
- Redis lease and heartbeat logic

- worker adapter launch contract
- artifact publish/retrieve flow
- approval block/unblock flow
- clarification pause/resume flow
- graph projection updates from outbox/events
- Vertex runtime env injection contract

### 18.3 End-to-end tests
- manager -> backend + frontend -> integration -> review
- blocked task + human answer + resume
- failed attempt + retry + route escalation
- reviewer rejection -> rework -> re-review
- artifact handoff across dependency edges
- orchestrator restart with pending work
- event stream and timeline reconstruction

### 18.4 Edge-case tests
1. two independent tasks run concurrently without contamination
2. blocked task does not block unrelated branch
3. hard dependencies gate unlock correctly
4. invalid worker transition is rejected

6. Redis lease expiry recovers safely
7. worker crash after upload before finalize is reconciled
8. Neo4j projection failure does not corrupt truth
9. artifact visibility does not leak across workflows
10. human answer attaches only to matching request
11. approval rejection prevents completion
12. retry preserves prior attempt history
13. separate worktrees avoid file corruption
14. large artifact retrieval is bounded
15. restart reconstructs dispatchable work
16. route fallback is recorded and explainable
17. resume policy chooses correct workspace behavior
18. unresolved hard dependency prevents completion
19. missing context returns typed miss instead of hallucinated success
20. telemetry exporter outage does not break execution

---

## 19. Diagrams (text form)

### 19.1 Runtime sequence

\`\`\`mermaid
sequenceDiagram
    participant H as Human/CLI
    participant O as Orchestrator
    participant DB as Postgres
    participant R as Redis
    participant C as Compiler
    participant W as OpenHands Worker
    participant X as Context Service
    participant A as Artifact Registry

    H->>O: submit task
    O->>DB: create workflow_run + root task
    O->>W: launch manager attempt (after compile)
    W->>X: get_task / search_memory
    W->>DB: indirect via services only
    W->>A: put_artifact(plan)
    O->>DB: persist task graph revision
    O->>R: enqueue runnable downstream tasks
\`\`\`

### 19.2 Domain class diagram

\`\`\`mermaid
classDiagram
    class Project
    class Team
    class AgentDefinition
    class WorkflowDefinition
    class WorkflowRun
    class Task
    class TaskEdge
    class TaskAttempt
    class Artifact
    class Decision
    class MemoryEntry
    class HumanRequest
    class ApprovalRequest
    class Event
    class ModelRoute
    class WorkspaceRecord

    Project --> Team
    Project --> AgentDefinition
    Project --> WorkflowDefinition
    WorkflowDefinition --> WorkflowRun
    WorkflowRun --> Task
    Task --> TaskEdge
    Task --> TaskAttempt
    TaskAttempt --> Artifact
    TaskAttempt --> Decision
    WorkflowRun --> Event
    Task --> HumanRequest
    Task --> ApprovalRequest
    TaskAttempt --> ModelRoute
    TaskAttempt --> WorkspaceRecord
\`\`\`

### 19.3 Service diagram

\`\`\`mermaid
classDiagram
    class OrchestratorService
    class WorkflowEngine
    class Scheduler
    class WorkerManager
    class ConfigCompiler
    class ContextService
    class ArtifactRegistry
    class ApprovalService
    class EventService
    class ModelRouter
    class GraphProjectionService
    class ObservabilityExporter
    class StorageUnitOfWork

    OrchestratorService --> WorkflowEngine
    OrchestratorService --> Scheduler
    OrchestratorService --> WorkerManager
    OrchestratorService --> ContextService
    OrchestratorService --> ArtifactRegistry
    OrchestratorService --> ApprovalService
    OrchestratorService --> EventService
    OrchestratorService --> ModelRouter
    OrchestratorService --> GraphProjectionService
    OrchestratorService --> ObservabilityExporter
    OrchestratorService --> StorageUnitOfWork
    WorkerManager --> ConfigCompiler
\`\`\`

---

## 20. Final implementation conclusion

Build AutoWeave as a **Vertex-AI-backed, OpenHands-powered multi-agent orchestration library** with **canonical Postgres truth**, **Redis coordination**, **Neo4j graph projection/retrieval**, **worker-isolated worktrees**, **typed context and artifact services**, and **library-owned observability export**.

            `
        };

        /* --- SPA State & Logic --- */
        const state = {
            payload: null,
            activeRunId: null,
            busy: false,
            initialLoadComplete: false
        };
        const ACTIVE_ATTEMPTS = new Set(["dispatching", "running", "paused", "needs_input"]);

        function escapeHtml(value) {
            return String(value ?? "")
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#39;");
        }

        function activeRun() {
            if (!state.payload || !Array.isArray(state.payload.runs)) return null;
            return state.payload.runs.find(r => r.id === state.activeRunId) || state.payload.selected_run || state.payload.runs[0] || null;
        }

        // --- DOM Elements ---
        const els = {
            loadingScreen: document.getElementById('loading-screen'),
            loadingProgress: document.getElementById('loading-progress'),
            loadingStatus: document.getElementById('loading-status'),
            app: document.getElementById('app'),
            navItems: document.querySelectorAll('.nav-item'),
            pageDocs: document.getElementById('page-docs'),
            pageAgents: document.getElementById('page-agents'),
            pagePlayground: document.getElementById('page-playground'),
            markdownContainer: document.getElementById('markdown-container'),
            agentsGrid: document.getElementById('agents-grid'),
            connectionDot: document.getElementById('connection-dot'),
            connectionText: document.getElementById('connection-text'),
            
            // Playground
            chatThread: document.getElementById('chat-thread'),
            composerInput: document.getElementById('composer-input'),
            composerDispatch: document.getElementById('composer-dispatch'),
            composerSubmit: document.getElementById('composer-submit'),
            composerHint: document.getElementById('composer-hint'),
            chatComposer: document.getElementById('chat-composer'),
            
            runSummaryId: document.getElementById('run-summary-id'),
            runSummaryPill: document.getElementById('run-summary-pill'),
            runSummaryDot: document.getElementById('run-summary-dot'),
            runSummaryStatus: document.getElementById('run-summary-status'),
            runOpStatus: document.getElementById('run-op-status'),
            runWorkers: document.getElementById('run-workers'),
            taskCount: document.getElementById('task-count'),
            taskList: document.getElementById('task-list')
        };

        // --- Navigation ---
        const pageRuns = document.getElementById('page-runs');
        function navigate(route) {
            route = route.replace('#', '') || 'playground';
            window.location.hash = route;
            
            // Docs routing handles sub-routes implicitly
            let mainRoute = route;
            if (["ARCHITECTURE", "DEPLOYMENT", "autoweave_diagrams_source", "autoweave_high_level_architecture", "autoweave_implementation_spec"].includes(route)) {
                mainRoute = 'docs';
            }
            
            els.navItems.forEach(el => {
                if(el.dataset.route) el.classList.remove('active');
            });
            const activeNav = document.querySelector(`.nav-item[data-route="${mainRoute}"]`);
            if (activeNav) activeNav.classList.add('active');

            els.pageDocs.classList.remove('active');
            els.pageAgents.classList.remove('active');
            els.pagePlayground.classList.remove('active');
            pageRuns.classList.remove('active');

            if (mainRoute === 'playground') {
                els.pagePlayground.classList.add('active');
                renderPlayground();
            } else if (mainRoute === 'runs') {
                pageRuns.classList.add('active');
                renderRuns();
            } else if (mainRoute === 'agents') {
                els.pageAgents.classList.add('active');
                renderAgents();
            } else if (mainRoute === 'docs') {
                els.pageDocs.classList.add('active');
                
                // Set nested active doc
                const docRoute = route === 'docs' ? 'ARCHITECTURE' : route;
                document.querySelectorAll('#docs-nav-group .nav-item').forEach(el => el.classList.remove('active'));
                const activeDocNav = document.querySelector(`#docs-nav-group .nav-item[data-doc="${docRoute}"]`);
                if (activeDocNav) activeDocNav.classList.add('active');
                
                const rawMarkdown = docs[docRoute] || '# Not Found\nThe requested page does not exist.';
                els.markdownContainer.innerHTML = parseMarkdown(rawMarkdown);
                if (window.mermaid) {
                    setTimeout(() => {
                        try { mermaid.init(undefined, document.querySelectorAll('.mermaid')); } catch(e) { console.error('Mermaid error', e); }
                    }, 50);
                }
            }
        }
        
        // Setup Docs click handlers
        document.querySelectorAll('#docs-nav-group .nav-item').forEach(item => {
            item.addEventListener('click', () => navigate(item.dataset.doc));
        });
        
        // Search functionality
        const docsSearch = document.getElementById('docs-search');
        docsSearch.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            document.querySelectorAll('#docs-nav-group .nav-item').forEach(el => {
                if (el.textContent.toLowerCase().includes(query)) {
                    el.style.display = '';
                } else {
                    el.style.display = 'none';
                }
            });
        });


        window.addEventListener('hashchange', () => navigate(window.location.hash));

        // --- Rendering ---
        
        function toggleRunExpanded(runId) {
            const el = document.getElementById('run-item-' + runId);
            if (el) el.classList.toggle('expanded');
        }

        function renderRuns() {
            const runsList = document.getElementById('runs-list');
            if (!state.payload || !state.payload.runs || state.payload.runs.length === 0) {
                runsList.innerHTML = `<div class="empty-state"><span class="material-symbols-outlined">history</span><p>No historical runs found.</p></div>`;
                return;
            }
            
            // Preserve expanded states
            const expandedIds = new Set();
            document.querySelectorAll('#runs-list .run-item.expanded').forEach(el => {
                expandedIds.add(el.id);
            });

            let html = '';
            state.payload.runs.forEach(run => {
                const tasks = run.tasks || [];
                let tasksHtml = '';
                tasks.forEach(task => {
                    let icon = "pending";
                    let stateClass = "state-pending";
                    
                    if (task.state === "succeeded" || task.state === "completed") {
                        icon = "check_circle"; stateClass = "state-success";
                    } else if (task.state === "running" || task.state === "dispatching") {
                        icon = "refresh"; stateClass = "state-running";
                    } else if (task.state === "failed" || task.state === "error") {
                        icon = "error"; stateClass = "state-failed";
                    }

                    tasksHtml += `
                    <div class="task-item">
                        <div class="task-icon"><span class="material-symbols-outlined ${stateClass}" style="font-size: 16px;">${icon}</span></div>
                        <div class="task-content">
                            <div class="task-header">
                                <div class="task-name">${escapeHtml(task.title || task.task_key)}</div>
                                <div class="task-state ${stateClass}">${escapeHtml(task.state)}</div>
                            </div>
                            <div class="task-desc">${escapeHtml(task.worker_summary || "No description")}</div>
                        </div>
                    </div>`;
                });
                
                const isRunning = run.execution_status === "running" || run.execution_status === "dispatching";
                const pillClass = isRunning ? "pill-running" : (run.execution_status === "completed" || run.execution_status === "succeeded" ? "pill-success" : "pill-idle");
                
                const runElementId = `run-item-${escapeHtml(run.id)}`;
                const expandedClass = expandedIds.has(runElementId) ? ' expanded' : '';
                html += `
                    <div id="${runElementId}" class="run-item${expandedClass}" onclick="toggleRunExpanded('${escapeHtml(run.id)}')">
                        <div class="run-item-header">
                            <div>
                                <div style="font-weight: 500; font-size: 14px; margin-bottom: 4px;">Run: ${escapeHtml(run.id || run.title)}</div>
                                <div style="font-size: 12px; color: var(--text-secondary);">${tasks.length} tasks</div>
                            </div>
                            <div class="status-pill ${pillClass}">
                                <div class="dot" style="width: 6px; height: 6px; border-radius: 50%;"></div>
                                <span>${escapeHtml(run.execution_status || "UNKNOWN").toUpperCase()}</span>
                            </div>
                        </div>
                        <div class="run-item-details" onclick="event.stopPropagation()">
                            <h4 style="margin-bottom: 12px; font-size: 12px; color: var(--text-secondary); text-transform: uppercase;">Execution Tasks</h4>
                            <div class="task-list" style="max-height: 400px;">
                                ${tasksHtml || '<div class="empty-state">No tasks executed</div>'}
                            </div>
                        </div>
                    </div>
                `;
            });
            runsList.innerHTML = html;
        }

        window.showAgentSidebar = function(agentName) {
            const agent = state.payload.agents.find(a => a.name === agentName);
            if (!agent) return;
            const sidebar = document.getElementById('agent-sidebar');
            const content = document.getElementById('agent-sidebar-content');
            
            const skillsHtml = (agent.primary_skills || []).map(skill => `<span class="skill-tag">${escapeHtml(skill)}</span>`).join('');
            
            // Check if active
            const activeRunData = activeRun();
            const activeTask = activeRunData?.tasks?.find(t => (t.state === 'running' || t.state === 'dispatching') && t.assigned_role === agent.role);
            
            let statusHtml = '';
            if (activeTask) {
                statusHtml = `
                    <div style="margin-top: 24px;">
                        <h4 style="margin-bottom: 12px; font-size: 12px; color: var(--text-secondary); text-transform: uppercase;">Current Task</h4>
                        <div class="task-item running">
                            <div class="task-icon"><span class="material-symbols-outlined state-running" style="font-size: 16px;">refresh</span></div>
                            <div class="task-content">
                                <div class="task-name">${escapeHtml(activeTask.title || activeTask.task_key)}</div>
                                <div class="task-desc">${escapeHtml(activeTask.worker_summary || "Working...")}</div>
                            </div>
                        </div>
                    </div>
                `;
            } else {
                statusHtml = `
                    <div style="margin-top: 24px; padding: 24px; text-align: center; border: 1px dashed var(--border-default); border-radius: 8px;">
                        <span class="material-symbols-outlined" style="font-size: 32px; color: var(--text-tertiary); margin-bottom: 8px;">snooze</span>
                        <div style="color: var(--text-secondary); font-size: 14px;">Agent is currently idle.</div>
                    </div>
                `;
            }

            content.innerHTML = `
                <div style="font-size: 12px; font-family: var(--font-mono); color: var(--text-tertiary); margin-bottom: 8px;">${escapeHtml(agent.role)}</div>
                <h2 style="font-size: 20px; font-weight: 600; margin-bottom: 16px;">${escapeHtml(agent.name)}</h2>
                <p style="color: var(--text-secondary); font-size: 14px; margin-bottom: 24px; line-height: 1.5;">${escapeHtml(agent.description)}</p>
                
                <h4 style="margin-bottom: 12px; font-size: 12px; color: var(--text-secondary); text-transform: uppercase;">Skills & Capabilities</h4>
                <div class="agent-skills" style="margin-bottom: 24px;">${skillsHtml}</div>
                
                ${statusHtml}
            `;
            sidebar.classList.add('open');
        };

        function renderAgents() {
            if (!state.payload || !state.payload.agents || state.payload.agents.length === 0) {
                els.agentsGrid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;"><span class="material-symbols-outlined">smart_toy</span><p>No agents configured in this project.</p></div>`;
                return;
            }

            let html = '';
            const activeRunData = activeRun();
            
            state.payload.agents.forEach(agent => {
                const skillsHtml = (agent.primary_skills || []).map(skill => `<span class="skill-tag">${escapeHtml(skill)}</span>`).join('');
                
                const isWorking = activeRunData?.tasks?.some(t => (t.state === 'running' || t.state === 'dispatching') && t.assigned_role === agent.role);
                const badgeHtml = isWorking ? `<div class="agent-live-badge"><div class="pulse-dot"></div>Working</div>` : '';
                
                html += `
                    <div class="agent-card" style="cursor: pointer;" onclick="window.showAgentSidebar('${escapeHtml(agent.name)}')">
                        ${badgeHtml}
                        <div class="agent-role">${escapeHtml(agent.role)}</div>
                        <div class="agent-name">${escapeHtml(agent.name)}</div>
                        <div class="agent-desc">${escapeHtml(agent.description)}</div>
                        <div class="agent-skills">${skillsHtml}</div>
                    </div>
                `;
            });
            els.agentsGrid.innerHTML = html;
        }

        function renderPlayground() {
            const run = activeRun();
            
            // Chat Pane
            const messages = run ? (run.chat_messages || []) : [];
            let chatHtml = "";
            
            if (!messages.length) {
                els.chatThread.innerHTML = `<div class="empty-state"><span class="material-symbols-outlined">forum</span><p>No chat history for this run.</p></div>`;
            } else {
                messages.forEach(msg => {
                    const isUser = msg.role === 'user';
                    chatHtml += `
                        <div class="chat-msg ${isUser ? 'msg-user' : 'msg-sys'}">
                            <div class="msg-role">${isUser ? '[YOU]' : '[SYS]'}</div>
                            <div class="msg-content">${escapeHtml(msg.text).replace(/\n/g, '<br/>')}</div>
                        </div>
                    `;
                });
                
                const openApprovals = (run.approval_requests || []).filter(r => r.status === 'requested');
                openApprovals.forEach(appr => {
                    chatHtml += `
                        <div class="chat-msg msg-sys">
                            <div class="msg-role" style="color: var(--warning)">[REQ]</div>
                            <div class="msg-content">
                                <div class="approval-card">
                                    <div class="approval-title">Approval Requested</div>
                                    <div>${escapeHtml(appr.reason)}</div>
                                    <div class="approval-actions">
                                        <button class="btn btn-approve" onclick="window.resolveApproval('${run.id}', '${appr.id}', true)">Approve</button>
                                        <button class="btn btn-reject" onclick="window.resolveApproval('${run.id}', '${appr.id}', false)">Reject</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                });
                
                els.chatThread.innerHTML = chatHtml;
                els.chatThread.scrollTop = els.chatThread.scrollHeight;
            }

            const hr = (run?.human_requests || []).find(r => r.status === 'open');
            els.composerHint.textContent = hr ? `Answering: ${hr.question}` : "";

            // DAG Pane
            if (!run) {
                els.runSummaryId.textContent = "No Active Run";
                els.runSummaryStatus.textContent = "IDLE";
                els.runSummaryPill.className = "status-pill pill-idle";
                els.runOpStatus.textContent = "-";
                els.runWorkers.textContent = "0";
                els.taskCount.textContent = "0 tasks";
                els.taskList.innerHTML = `<div class="empty-state"><span class="material-symbols-outlined">account_tree</span><p>Awaiting workflow execution</p></div>`;
                return;
            }

            els.runSummaryId.textContent = escapeHtml(run.id || run.title);
            els.runOpStatus.textContent = escapeHtml(run.operator_status || "Unknown");
            
            const attempts = (run.attempts || []).filter(a => ACTIVE_ATTEMPTS.has(a.state));
            els.runWorkers.textContent = attempts.length.toString();

            const isRunning = run.execution_status === "running" || run.execution_status === "dispatching";
            const isSuccess = run.execution_status === "completed" || run.execution_status === "succeeded";
            
            if (isRunning) {
                els.runSummaryPill.className = "status-pill pill-running";
                els.runSummaryStatus.textContent = "RUNNING";
            } else if (isSuccess) {
                els.runSummaryPill.className = "status-pill pill-success";
                els.runSummaryStatus.textContent = "COMPLETED";
            } else {
                els.runSummaryPill.className = "status-pill pill-idle";
                els.runSummaryStatus.textContent = escapeHtml(run.execution_status || "UNKNOWN").toUpperCase();
            }

            const tasks = run.tasks || [];
            els.taskCount.textContent = `${tasks.length} tasks`;

            let tasksHtml = "";
            if (!tasks.length) {
                tasksHtml = `<div class="empty-state"><span class="material-symbols-outlined">analytics</span><p>End of Pipeline</p></div>`;
            } else {
                tasks.forEach(task => {
                    let icon = "pending";
                    let stateClass = "state-pending";
                    let rowClass = "task-item";
                    
                    if (task.state === "succeeded" || task.state === "completed") {
                        icon = "check_circle";
                        stateClass = "state-success";
                    } else if (task.state === "running" || task.state === "dispatching") {
                        icon = "refresh";
                        stateClass = "state-running";
                        rowClass += " running";
                    } else if (task.state === "failed" || task.state === "error") {
                        icon = "error";
                        stateClass = "state-failed";
                    }

                    tasksHtml += `
                    <div class="${rowClass}">
                        <div class="task-icon">
                            <span class="material-symbols-outlined ${stateClass}" style="font-size: 16px;">${icon}</span>
                        </div>
                        <div class="task-content">
                            <div class="task-header">
                                <div class="task-name">${escapeHtml(task.title || task.task_key)}</div>
                                <div class="task-state ${stateClass}">${escapeHtml(task.state)}</div>
                            </div>
                            <div class="task-desc">${escapeHtml(task.worker_summary || "No description")}</div>
                            <div class="task-key">${escapeHtml(task.task_key)}</div>
                        </div>
                    </div>`;
                });
            }
            els.taskList.innerHTML = tasksHtml;
        }

        // --- API & State Management ---
        async function postJson(path, payload) {
            const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
            if (!response.ok) throw new Error(await response.text() || `${path} failed`);
            return await response.json();
        }

        async function loadState() {
            if (state.busy) return;
            state.busy = true;
            try {

                
                const response = await fetch("/api/state?limit=8", { cache: "no-store" });
                const payload = await response.json();
                
                if (!state.initialLoadComplete) {
                    if (payload.status === 'loading') {
                        // Smoothly advance progress bar to 85% maximum during loading
                        const currentWidth = parseFloat(els.loadingProgress.style.width) || 10;
                        if (currentWidth < 85) {
                            els.loadingProgress.style.width = (currentWidth + (85 - currentWidth) * 0.2) + '%';
                        }
                        els.loadingStatus.textContent = "Loading dependencies... Background processes running.";
                    } else {
                        els.loadingProgress.style.width = '100%';
                        els.loadingStatus.textContent = "READY";
                        setTimeout(() => {
                            els.loadingScreen.classList.add('hidden');
                            els.app.classList.add('visible');
                            state.initialLoadComplete = true;
                            // Start regular polling once initialized
                            startPolling(4000);
                        }, 400);
                    }
                }

                state.payload = payload;
                const runIds = new Set((payload.runs || []).map((run) => run.id));
                if (!state.activeRunId || !runIds.has(state.activeRunId)) {
                    state.activeRunId = payload.selected_run_id || payload.selected_run?.id || payload.runs?.[0]?.id || null;
                }
                
                els.connectionDot.className = "status-dot connected";
                els.connectionText.textContent = "Connected";
                
                if (window.location.hash.includes("playground")) renderPlayground();
                if (window.location.hash.includes("agents")) renderAgents();
                if (window.location.hash.includes("runs")) renderRuns();
                
            } catch (error) {
                els.connectionDot.className = "status-dot disconnected";
                els.connectionText.textContent = "Disconnected";
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
                    dispatch: els.composerDispatch.value === "true",
                    max_steps: 8,
                });
                await loadState();
            } catch (error) {
                els.composerHint.textContent = `Error: ${error.message}`;
            }
        };

        els.chatComposer.addEventListener("submit", async (event) => {
            event.preventDefault();
            const message = els.composerInput.value.trim();
            if (!message) return;
            
            const run = activeRun();
            const hr = (run?.human_requests || []).find(r => r.status === 'open');
            const payload = { message, dispatch: els.composerDispatch.value === "true", max_steps: 8 };
            
            if (run && hr) {
                payload.workflow_run_id = run.id;
                payload.human_request_id = hr.id;
            }
            
            els.composerSubmit.disabled = true;
            els.composerInput.value = "";
            els.composerHint.textContent = "Sending...";
            
            try {
                await postJson("/api/chat", payload);
                els.composerHint.textContent = "";
                await loadState();
            } catch (error) {
                els.composerHint.textContent = `Error: ${error.message}`;
            } finally {
                els.composerSubmit.disabled = false;
            }
        });
        
        // --- Initialization ---
        // Setup nav listeners
        els.navItems.forEach(item => {
            item.addEventListener('click', () => navigate(item.dataset.route));
        });

        // Start loading sequence
        els.loadingProgress.style.width = '10%';
        navigate(window.location.hash);
        
        let pollInterval;
        function startPolling(ms) {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = window.setInterval(loadState, ms);
        }
        
        // Fast initial poll until loaded
        loadState();
        startPolling(2000);

    </script>
</body>
</html>"""
