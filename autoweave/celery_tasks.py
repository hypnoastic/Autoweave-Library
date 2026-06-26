"""Celery worker tasks for queued AutoWeave workflow execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from celery import shared_task

from autoweave.celery_queue import (
    WORKFLOW_TASK_NAME,
    create_autoweave_celery_app,
    should_requeue_report,
    workflow_report_to_payload,
)
from autoweave.local_runtime import build_local_runtime


@shared_task(name=WORKFLOW_TASK_NAME, bind=True)
def dispatch_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(payload.get("root", ""))).expanduser().resolve()
    environ = payload.get("environ")
    if not isinstance(environ, dict):
        environ = None
    action = str(payload.get("action", "continue_workflow")).strip().lower()
    workflow_run_id = str(payload.get("workflow_run_id", "")).strip() or None
    request = str(payload.get("request", "")).strip()
    dispatch = bool(payload.get("dispatch", True))
    max_steps = max(1, int(payload.get("max_steps", 8)))
    human_request_id = str(payload.get("human_request_id", "")).strip() or None
    approval_request_id = str(payload.get("approval_request_id", "")).strip() or None
    approved_raw = payload.get("approved")
    approved = bool(approved_raw) if approved_raw is not None else None

    with build_local_runtime(root=root, environ=environ, workflow_run_id=workflow_run_id) as runtime:
        if action == "run_workflow":
            report = runtime.run_workflow(request=request, dispatch=dispatch, max_steps=max_steps)
        elif action == "continue_workflow":
            report = runtime.continue_workflow_run(
                workflow_run_id=workflow_run_id or "",
                dispatch=dispatch,
                max_steps=max_steps,
            )
        elif action == "answer_human":
            report = runtime.answer_human_request(
                workflow_run_id=workflow_run_id or "",
                request_id=human_request_id or "",
                answer_text=request,
                answered_by="operator",
                dispatch=dispatch,
                max_steps=max_steps,
            )
        elif action == "resolve_approval":
            report = runtime.resolve_approval_request(
                workflow_run_id=workflow_run_id or "",
                request_id=approval_request_id or "",
                approved=bool(approved),
                resolved_by="operator",
                dispatch=dispatch,
                max_steps=max_steps,
            )
        else:  # pragma: no cover - defensive guard
            raise ValueError(f"unknown Celery workflow action {action!r}")

    result_payload = workflow_report_to_payload(report)
    if should_requeue_report(report, dispatch=dispatch):
        celery_app = create_autoweave_celery_app(root=root, environ=environ)
        next_result = celery_app.send_task(
            WORKFLOW_TASK_NAME,
            kwargs={
                "payload": {
                    **payload,
                    "action": "continue_workflow",
                    "workflow_run_id": report.workflow_run_id,
                    "request": report.request,
                }
            },
        )
        result_payload["requeued"] = True
        result_payload["next_celery_task_id"] = next_result.id
    else:
        result_payload["requeued"] = False
    return result_payload
