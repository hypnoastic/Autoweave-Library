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
            display: flex;
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

            <div class="nav-group">
                <div class="nav-title">Docs</div>
                <a class="nav-item active" data-route="overview">
                    <span class="material-symbols-outlined">book</span> Overview
                </a>
                <a class="nav-item" data-route="getting-started">
                    <span class="material-symbols-outlined">rocket_launch</span> Getting Started
                </a>
                <a class="nav-item" data-route="concepts">
                    <span class="material-symbols-outlined">architecture</span> Concepts
                </a>
                <a class="nav-item" data-route="api-reference">
                    <span class="material-symbols-outlined">api</span> API Reference
                </a>
            </div>

            <div class="nav-group">
                <div class="nav-title">Operate</div>
                <a class="nav-item" data-route="playground">
                    <span class="material-symbols-outlined">play_circle</span> Playground
                </a>
                <a class="nav-item" data-route="agents">
                    <span class="material-symbols-outlined">smart_toy</span> Agents
                </a>
            </div>

            <div class="nav-group">
                <div class="nav-title">Project</div>
                <a class="nav-item" data-route="project-info">
                    <span class="material-symbols-outlined">fact_check</span> Project Info
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
            <div id="page-docs" class="page-container active">
                <div class="prose-content markdown-body" id="markdown-container">
                    <!-- Markdown rendered here -->
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
            let html = md.replace(/```(?:[a-z]+)?\\n([\\s\\S]*?)```/g, (match, code) => {
                codeBlocks.push(code.replace(/</g, '&lt;').replace(/>/g, '&gt;'));
                return \`__CODE_BLOCK_\${codeBlocks.length - 1}__\`;
            });
            
            // Inline code
            html = html.replace(/\`([^\`]+)\`/g, '<code>$1</code>');
            
            // Headers
            html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
            html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
            html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
            
            // Bold & Italic
            html = html.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
            html = html.replace(/\\*(.*?)\\*/g, '<em>$1</em>');
            
            // Links
            html = html.replace(/\\[([^]+)\\]\\(([^)]+)\\)/g, '<a href="$2">$1</a>');
            
            // Lists (Simple)
            html = html.replace(/^\\* (.*$)/gim, '<ul><li>$1</li></ul>');
            html = html.replace(/<\\/ul>\\n<ul>/g, ''); // merge adjacent lists
            
            // Paragraphs
            html = html.replace(/^([^<\\s].*)$/gim, '<p>$1</p>');
            
            // Restore code blocks
            html = html.replace(/__CODE_BLOCK_(\\d+)__/g, (match, index) => {
                return \`<pre><code>\${codeBlocks[index]}</code></pre>\`;
            });
            
            // Clean up empty paragraphs
            html = html.replace(/<p><\\/p>/g, '');
            
            return html;
        }

        /* --- Content Store --- */
        const docs = {
            'overview': \`
# AutoWeave Library

AutoWeave is a terminal-first multi-agent orchestration library built around OpenHands remote workers and Vertex AI.

This package provides the runtime execution engine, durable workflow state management, Celery queue integration, human-in-the-loop coordination, and local monitoring primitives.

It is designed to be installed as a pure Python dependency by downstream products, keeping execution semantics and durable state decoupled from product-facing surfaces.

## Core Capabilities
* **Workflow Orchestration**: Define, compile, and execute DAGs of agentic tasks.
* **Durable State**: Resume paused runs, track attempts, and persist context safely.
* **Human-in-the-Loop**: Native primitives for pausing execution to request approvals or clarifications.
* **Queue Dispatch**: Offload long-running tasks to Celery workers.
* **Local Monitoring**: Inspect local runs natively via this lightweight UI.

## Architecture
AutoWeave separates the **Product Shell** from the **Runtime Engine**. This library *is* the Runtime Engine.
User requests are passed to the \\\`compiler\\\`. It takes a natural language request, grounds it in repository context, and emits an execution DAG of \\\`Tasks\\\`.
Tasks are routed to an assigned \\\`role\\\` and optionally dispatched to Celery workers.
            \`,
            'getting-started': \`
# Getting Started

AutoWeave Library is published as a Python package and runs locally.

## Prerequisites
* Python >= 3.10
* A local environment map (e.g. \\\`.env.local\\\`) containing your Vertex AI, Postgres, and Redis connection URIs if running the full persistent stack.

## Installation

Install via uv (Recommended):
\`\`\`bash
uv pip install autoweave
\`\`\`

Install via pip:
\`\`\`bash
pip install autoweave
\`\`\`

## Initialize a Project
AutoWeave requires a project directory to store local configurations.
\`\`\`bash
autoweave new-project ./my-weave-project
autoweave bootstrap --root ./my-weave-project
\`\`\`

## Run a Simple Workflow
\`\`\`bash
autoweave run-workflow \\
    --root ./my-weave-project \\
    --request "Write a script that prints Hello World"
\`\`\`
            \`,
            'concepts': \`
# Concepts & Usage

## 1. Workflow Compiler
User requests are passed to the \\\`compiler\\\`. It takes a natural language request, grounds it in repository context (Neo4j/Vector DB), and emits an execution DAG of \\\`Tasks\\\`.

## 2. Execution DAG & Tasks
Workflows are modeled as a DAG. Each \\\`Task\\\` is routed to an assigned \\\`role\\\` (e.g., Code Writer, QA Reviewer).

## 3. Human Approval Pauses
When an agent determines it needs human input, it emits an \\\`ApprovalRequest\\\`. The runtime pauses the task. The web layer (or local UI) captures this and prompts the user. Responding to the request resumes the execution DAG automatically.

## Usage Example: Programmatic API
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
            \`,
            'api-reference': \`
# API Reference

AutoWeave exposes a minimal public surface area for external Python consumption.

### \\\`build_local_runtime(root_path: Path) -> LocalRuntime\\\`
Constructs the full dependency-injected runtime engine. Requires a configured \\\`.env.local\\\` inside the \\\`root_path\\\`.

### \\\`bootstrap_project(root_path: Path) -> None\\\`
Scaffolds the necessary fixtures, local DB structure, and template files into a target directory.

### \\\`migrate_project(root_path: Path) -> None\\\`
Refreshes template-managed files to newer packaged defaults if the library version is updated.

### \\\`load_env_map(root_path: Path) -> dict\\\`
Loads and merges the local environment variables cleanly, respecting standard \\\`.env\\\` hierarchies.

### \\\`AttemptState\\\` / \\\`TaskState\\\`
Enums representing the durable lifecycle states of workflow nodes. Valid states include \\\`pending\\\`, \\\`running\\\`, \\\`paused\\\`, \\\`succeeded\\\`, \\\`failed\\\`.
            \`,
            'project-info': \`
# Project Info

AutoWeave is tested rigorously to ensure production-grade reliability of the orchestration engine.

## Testing & Quality
We enforce a strict **80%+ overall line coverage** threshold. Pull requests failing this constraint will block merging in CI.

1. **Unit Tests**: Validates compilation, template generation, and state machine transitions.
2. **Integration Tests**: Tests full orchestration loops via \\\`test_orchestration.py\\\` using mock worker executors.
3. **Queue/Celery Tests**: Validates \\\`test_celery_queue.py\\\` behavior.
4. **Storage Tests**: \\\`test_storage_durable.py\\\` verifies Postgres/SQLite persistence schemas.
5. **UI / Documentation Tests**: Headless browser tests (Playwright) ensure this local dashboard functions flawlessly.

Run locally:
\`\`\`bash
make test
\`\`\`

## Security
As a runtime engine executing agent-generated commands, security is paramount.
* **Worker Isolation**: Remote workers (OpenHands) must run inside sandboxed environments. AutoWeave orchestrates them but *does not* provide the sandbox itself.
* **Validations**: Input validation is strictly enforced via \\\`pydantic\\\` for all runtime state models. No unsafe \\\`eval()\\\` or \\\`exec()\\\` is used.

## CI/CD
AutoWeave uses GitHub Actions for continuous integration and delivery.
* **Code Quality**: Ruff linting, formatting, and strict mypy typechecking.
* **Security Scans**: pip-audit and CodeQL static analysis.
* **Releases**: Automated publishing to PyPI using Trusted Publishing (OIDC).
            \`
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
        function navigate(route) {
            route = route.replace('#', '') || 'overview';
            window.location.hash = route;
            
            els.navItems.forEach(el => el.classList.remove('active'));
            const activeNav = document.querySelector(\`.nav-item[data-route="\${route}"]\`);
            if (activeNav) activeNav.classList.add('active');

            els.pageDocs.classList.remove('active');
            els.pageAgents.classList.remove('active');
            els.pagePlayground.classList.remove('active');

            if (route === 'playground') {
                els.pagePlayground.classList.add('active');
                renderPlayground();
            } else if (route === 'agents') {
                els.pageAgents.classList.add('active');
                renderAgents();
            } else {
                els.pageDocs.classList.add('active');
                const rawMarkdown = docs[route] || '# Not Found\\nThe requested page does not exist.';
                els.markdownContainer.innerHTML = parseMarkdown(rawMarkdown);
            }
        }

        window.addEventListener('hashchange', () => navigate(window.location.hash));

        // --- Rendering ---
        function renderAgents() {
            if (!state.payload || !state.payload.agents || state.payload.agents.length === 0) {
                els.agentsGrid.innerHTML = \`<div class="empty-state" style="grid-column: 1 / -1;"><span class="material-symbols-outlined">smart_toy</span><p>No agents configured in this project.</p></div>\`;
                return;
            }

            let html = '';
            state.payload.agents.forEach(agent => {
                const skillsHtml = (agent.primary_skills || []).map(skill => \`<span class="skill-tag">\${escapeHtml(skill)}</span>\`).join('');
                html += \`
                    <div class="agent-card">
                        <div class="agent-role">\${escapeHtml(agent.role)}</div>
                        <div class="agent-name">\${escapeHtml(agent.name)}</div>
                        <div class="agent-desc">\${escapeHtml(agent.description)}</div>
                        <div class="agent-skills">\${skillsHtml}</div>
                    </div>
                \`;
            });
            els.agentsGrid.innerHTML = html;
        }

        function renderPlayground() {
            const run = activeRun();
            
            // Chat Pane
            const messages = run ? (run.chat_messages || []) : [];
            let chatHtml = "";
            
            if (!messages.length) {
                els.chatThread.innerHTML = \`<div class="empty-state"><span class="material-symbols-outlined">forum</span><p>No chat history for this run.</p></div>\`;
            } else {
                messages.forEach(msg => {
                    const isUser = msg.role === 'user';
                    chatHtml += \`
                        <div class="chat-msg \${isUser ? 'msg-user' : 'msg-sys'}">
                            <div class="msg-role">\${isUser ? '[YOU]' : '[SYS]'}</div>
                            <div class="msg-content">\${escapeHtml(msg.text).replace(/\\n/g, '<br/>')}</div>
                        </div>
                    \`;
                });
                
                const openApprovals = (run.approval_requests || []).filter(r => r.status === 'requested');
                openApprovals.forEach(appr => {
                    chatHtml += \`
                        <div class="chat-msg msg-sys">
                            <div class="msg-role" style="color: var(--warning)">[REQ]</div>
                            <div class="msg-content">
                                <div class="approval-card">
                                    <div class="approval-title">Approval Requested</div>
                                    <div>\${escapeHtml(appr.reason)}</div>
                                    <div class="approval-actions">
                                        <button class="btn btn-approve" onclick="window.resolveApproval('\${run.id}', '\${appr.id}', true)">Approve</button>
                                        <button class="btn btn-reject" onclick="window.resolveApproval('\${run.id}', '\${appr.id}', false)">Reject</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    \`;
                });
                
                els.chatThread.innerHTML = chatHtml;
                els.chatThread.scrollTop = els.chatThread.scrollHeight;
            }

            const hr = (run?.human_requests || []).find(r => r.status === 'open');
            els.composerHint.textContent = hr ? \`Answering: \${hr.question}\` : "";

            // DAG Pane
            if (!run) {
                els.runSummaryId.textContent = "No Active Run";
                els.runSummaryStatus.textContent = "IDLE";
                els.runSummaryPill.className = "status-pill pill-idle";
                els.runOpStatus.textContent = "-";
                els.runWorkers.textContent = "0";
                els.taskCount.textContent = "0 tasks";
                els.taskList.innerHTML = \`<div class="empty-state"><span class="material-symbols-outlined">account_tree</span><p>Awaiting workflow execution</p></div>\`;
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
            els.taskCount.textContent = \`\${tasks.length} tasks\`;

            let tasksHtml = "";
            if (!tasks.length) {
                tasksHtml = \`<div class="empty-state"><span class="material-symbols-outlined">analytics</span><p>End of Pipeline</p></div>\`;
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

                    tasksHtml += \`
                    <div class="\${rowClass}">
                        <div class="task-icon">
                            <span class="material-symbols-outlined \${stateClass}" style="font-size: 16px;">\${icon}</span>
                        </div>
                        <div class="task-content">
                            <div class="task-header">
                                <div class="task-name">\${escapeHtml(task.title || task.task_key)}</div>
                                <div class="task-state \${stateClass}">\${escapeHtml(task.state)}</div>
                            </div>
                            <div class="task-desc">\${escapeHtml(task.worker_summary || "No description")}</div>
                            <div class="task-key">\${escapeHtml(task.task_key)}</div>
                        </div>
                    </div>\`;
                });
            }
            els.taskList.innerHTML = tasksHtml;
        }

        // --- API & State Management ---
        async function postJson(path, payload) {
            const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
            if (!response.ok) throw new Error(await response.text() || \`\${path} failed\`);
            return await response.json();
        }

        async function loadState() {
            if (state.busy) return;
            state.busy = true;
            try {
                if (!state.initialLoadComplete) {
                    els.loadingProgress.style.width = '50%';
                }
                
                const response = await fetch("/api/state?limit=8", { cache: "no-store" });
                const payload = await response.json();
                
                if (!state.initialLoadComplete) {
                    if (payload.status === 'loading') {
                        els.loadingProgress.style.width = '80%';
                        els.loadingStatus.textContent = "WAITING FOR RUNTIME...";
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
                els.composerHint.textContent = \`Error: \${error.message}\`;
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
                els.composerHint.textContent = \`Error: \${error.message}\`;
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
        els.loadingProgress.style.width = '20%';
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
