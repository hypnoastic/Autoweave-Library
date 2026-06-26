"""WSGI entrypoint for the lightweight AutoWeave operator console."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from autoweave.monitoring.dashboard_page import render_dashboard_page
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
            return self._respond(
                start_response,
                "200 OK",
                render_dashboard_page().encode("utf-8"),
                "text/html; charset=utf-8",
            )
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
