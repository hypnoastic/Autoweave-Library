"""Worker runtime scaffolding and workspace policy helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from autoweave.config_models import VertexConfig
from autoweave.models import ArtifactRecord, ArtifactStatus, ModelRouteRecord, TaskAttemptRecord, TaskRecord
from autoweave.exceptions import ConfigurationError


def build_vertex_worker_env(
    *,
    project: str,
    location: str,
    service_account_file: str | Path,
) -> dict[str, str]:
    """Materialize the worker-side Vertex environment from canonical settings."""

    if not project:
        raise ConfigurationError("VERTEXAI_PROJECT is required")
    if not location:
        raise ConfigurationError("VERTEXAI_LOCATION is required")

    credential_text = str(service_account_file).strip()
    if not credential_text:
        raise ConfigurationError("VERTEXAI_SERVICE_ACCOUNT_FILE is required")
    credential_path = Path(credential_text)

    return {
        "VERTEXAI_PROJECT": project,
        "VERTEXAI_LOCATION": location,
        "VERTEXAI_SERVICE_ACCOUNT_FILE": str(credential_path),
        "GOOGLE_APPLICATION_CREDENTIALS": str(credential_path),
    }


@dataclass(slots=True, frozen=True)
class OpenHandsServiceCall:
    """Uniform response shape for OpenHands agent-server calls."""

    ok: bool
    method: str
    path: str
    status_code: int | None = None
    response_json: dict[str, Any] = field(default_factory=dict)
    response_text: str = ""
    error: str | None = None

    @property
    def conversation_id(self) -> str | None:
        value = self.response_json.get("id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @property
    def execution_status(self) -> str | None:
        value = self.response_json.get("execution_status")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None


@dataclass(slots=True, frozen=True)
class OpenHandsStreamEvent:
    """Normalized event emitted by OpenHands conversation runs."""

    event_type: str
    message: str = ""
    payload_json: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] | None = None
    outcome: str | None = None
    terminal: bool = False
    requires_human: bool = False
    approval_required: bool = False
    empty_response: bool = False


def normalize_openhands_stream_event(event: Mapping[str, Any] | OpenHandsStreamEvent) -> OpenHandsStreamEvent:
    """Normalize a raw OpenHands event payload into a typed record."""

    if isinstance(event, OpenHandsStreamEvent):
        return event
    payload = dict(event)
    kind = str(payload.get("kind", "")).strip()
    if kind:
        normalized = _normalize_openhands_api_event(payload, kind)
        if normalized is not None:
            return normalized
    payload_json = payload.get("payload_json")
    if not isinstance(payload_json, dict):
        payload_json = {k: v for k, v in payload.items() if k not in {"event_type", "type", "message", "text", "artifact", "outcome", "terminal", "requires_human", "approval_required"}}
    artifact = payload.get("artifact")
    if artifact is not None and not isinstance(artifact, dict):
        artifact = {"content": artifact}
    return OpenHandsStreamEvent(
        event_type=str(payload.get("event_type") or payload.get("type") or "progress"),
        message=str(payload.get("message") or payload.get("text") or ""),
        payload_json=payload_json,
        artifact=artifact if isinstance(artifact, dict) else None,
        outcome=(str(payload["outcome"]) if payload.get("outcome") is not None else None),
        terminal=bool(payload.get("terminal", False)),
        requires_human=bool(payload.get("requires_human", False)),
        approval_required=bool(payload.get("approval_required", False)),
        empty_response=bool(payload.get("empty_response", False)),
    )


def extract_openhands_stream_events(payload: Mapping[str, Any]) -> list[OpenHandsStreamEvent]:
    """Extract a stream event list from an OpenHands API response payload."""

    for key in ("events", "stream", "messages"):
        raw_events = payload.get(key)
        if isinstance(raw_events, list):
            return [normalize_openhands_stream_event(item) for item in raw_events if isinstance(item, Mapping) or isinstance(item, OpenHandsStreamEvent)]
    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        return [normalize_openhands_stream_event(item) for item in raw_items if isinstance(item, Mapping) or isinstance(item, OpenHandsStreamEvent)]
    return []


def _normalize_openhands_api_event(payload: dict[str, Any], kind: str) -> OpenHandsStreamEvent | None:
    kind_lower = kind.lower()
    if "conversationstateupdateevent" in kind_lower:
        key = str(payload.get("key") or "")
        value = str(payload.get("value") or "")
        event_payload = {"kind": kind, "key": key, "value": value}
        if key == "execution_status":
            if value == "finished":
                return OpenHandsStreamEvent(
                    event_type="complete",
                    message="conversation finished",
                    payload_json=event_payload,
                    outcome="success",
                    terminal=True,
                )
            if value in {"error", "stuck"}:
                return OpenHandsStreamEvent(
                    event_type="error",
                    message=f"conversation {value}",
                    payload_json=event_payload,
                    outcome=value,
                    terminal=True,
                )
            if value == "waiting_for_confirmation":
                return OpenHandsStreamEvent(
                    event_type="confirmation",
                    message="conversation waiting for confirmation",
                    payload_json=event_payload,
                    approval_required=True,
                )
            if value == "paused":
                return OpenHandsStreamEvent(
                    event_type="paused",
                    message="conversation paused",
                    payload_json=event_payload,
                    requires_human=True,
                )
            return OpenHandsStreamEvent(
                event_type="progress",
                message=f"conversation {value}",
                payload_json=event_payload,
                outcome=value or None,
            )
        return OpenHandsStreamEvent(
            event_type="progress",
            message=f"{key} updated",
            payload_json=event_payload,
        )
    if "conversationerrorevent" in kind_lower or "agenterrorevent" in kind_lower:
        detail = str(payload.get("detail") or payload.get("message") or payload.get("code") or "worker error")
        return OpenHandsStreamEvent(
            event_type="error",
            message=detail,
            payload_json={"kind": kind, **payload},
            outcome="error",
            terminal=True,
        )
    if "pauseevent" in kind_lower:
        return OpenHandsStreamEvent(
            event_type="paused",
            message="conversation paused",
            payload_json={"kind": kind, **payload},
            requires_human=True,
        )
    if "messageevent" in kind_lower:
        llm_message = payload.get("llm_message")
        if not isinstance(llm_message, Mapping):
            llm_message = {}
        content = llm_message.get("content")
        message = _message_text(content)
        role = str(llm_message.get("role") or payload.get("source") or "")
        tool_calls = llm_message.get("tool_calls")
        tool_call_count = len(tool_calls) if isinstance(tool_calls, list) else 0
        content_part_types = _content_part_types(content)
        provider_specific_fields = llm_message.get("provider_specific_fields")
        reasoning_content = llm_message.get("reasoning_content")
        reasoning_content_present = isinstance(reasoning_content, str) and bool(reasoning_content.strip())
        empty_response = role == "assistant" and not message.strip() and tool_call_count == 0
        return OpenHandsStreamEvent(
            event_type="empty_response" if empty_response else "message",
            message=message,
            payload_json={
                "kind": kind,
                "role": role,
                "source": payload.get("source", ""),
                "tool_call_count": tool_call_count,
                "content_part_types": content_part_types,
                "provider_specific_fields_present": isinstance(provider_specific_fields, Mapping),
                "reasoning_content_present": reasoning_content_present,
            },
            empty_response=empty_response,
        )
    if "observationevent" in kind_lower or "actionevent" in kind_lower or "tokenevent" in kind_lower:
        return OpenHandsStreamEvent(
            event_type="progress",
            message=str(payload.get("message") or payload.get("content") or payload.get("tool_name") or kind),
            payload_json={"kind": kind, **payload},
        )
    return None


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(part for part in parts if part)


def _content_part_types(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    part_types: list[str] = []
    for item in content:
        if isinstance(item, str):
            part_types.append("text")
            continue
        if not isinstance(item, Mapping):
            part_types.append(type(item).__name__)
            continue
        part_type = item.get("type")
        if isinstance(part_type, str) and part_type.strip():
            part_types.append(part_type)
            continue
        if "text" in item:
            part_types.append("text")
            continue
        part_types.append("unknown")
    return part_types


def stream_event_to_artifact(
    event: OpenHandsStreamEvent,
    *,
    task: TaskRecord,
    attempt: TaskAttemptRecord,
) -> ArtifactRecord | None:
    """Convert a terminal artifact-bearing stream event into a canonical artifact record."""

    artifact = event.artifact
    if artifact is None and "artifact" not in event.payload_json:
        return None
    artifact_payload = artifact or {}
    if not artifact_payload and isinstance(event.payload_json.get("artifact"), dict):
        artifact_payload = event.payload_json["artifact"]
    status_value = str(artifact_payload.get("status", ArtifactStatus.FINAL.value))
    status = ArtifactStatus.FINAL if status_value == ArtifactStatus.FINAL.value else ArtifactStatus.DRAFT
    metadata_json = artifact_payload.get("metadata_json")
    if not isinstance(metadata_json, dict):
        metadata_json = {}
    summary = str(
        artifact_payload.get("summary")
        or event.message
        or artifact_payload.get("content")
        or ""
    )
    return ArtifactRecord(
        workflow_run_id=task.workflow_run_id,
        task_id=task.id,
        task_attempt_id=attempt.id,
        produced_by_role=task.assigned_role,
        artifact_type=str(artifact_payload.get("artifact_type") or event.payload_json.get("artifact_type") or "result"),
        title=str(artifact_payload.get("title") or task.title),
        summary=summary,
        status=status,
        version=int(artifact_payload.get("version", 1)),
        storage_uri=str(artifact_payload.get("storage_uri") or artifact_payload.get("uri") or ""),
        checksum=str(artifact_payload.get("checksum") or artifact_payload.get("sha256") or ""),
        metadata_json=metadata_json,
    )


@dataclass(slots=True)
class OpenHandsAgentServerClient:
    """Thin httpx-based client for the OpenHands agent-server path."""

    base_url: str
    api_key: str | None = None
    bootstrap_path: str = "/api/conversations"
    timeout_seconds: float = 30.0
    client: httpx.Client | None = None
    transport: httpx.BaseTransport | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self.client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                headers=headers,
                transport=self.transport,
                follow_redirects=True,
            )

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def __enter__(self) -> "OpenHandsAgentServerClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def health_probe(self) -> OpenHandsServiceCall:
        return self._request("GET", "/health")

    def bootstrap_attempt(self, launch_payload: dict[str, Any]) -> OpenHandsServiceCall:
        if self.bootstrap_path == "/api/conversations":
            request_payload = build_openhands_conversation_request(launch_payload)
            return self._request("POST", self.bootstrap_path, json=request_payload)
        return self._request("POST", self.bootstrap_path, json=launch_payload)

    def get_conversation(self, conversation_id: str) -> OpenHandsServiceCall:
        return self._request("GET", f"/api/conversations/{conversation_id}")

    def run_conversation(self, conversation_id: str) -> OpenHandsServiceCall:
        return self._request("POST", f"/api/conversations/{conversation_id}/run")

    def search_conversation_events(
        self,
        conversation_id: str,
        *,
        page_id: str | None = None,
        limit: int = 100,
    ) -> OpenHandsServiceCall:
        params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
        if page_id:
            params["page_id"] = page_id
        return self._request(
            "GET",
            f"/api/conversations/{conversation_id}/events/search",
            params=params,
        )

    def list_all_conversation_events(self, conversation_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_page_id: str | None = None
        while True:
            response = self.search_conversation_events(
                conversation_id,
                page_id=next_page_id,
                limit=limit,
            )
            if not response.ok:
                break
            page_items = response.response_json.get("items")
            if isinstance(page_items, list):
                items.extend(item for item in page_items if isinstance(item, dict))
            next_page = response.response_json.get("next_page_id")
            if not isinstance(next_page, str) or not next_page.strip():
                break
            next_page_id = next_page
        return items

    def wait_for_conversation(
        self,
        conversation_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = 1.0,
    ) -> OpenHandsServiceCall:
        deadline = time.monotonic() + max(timeout_seconds, 0.1)
        latest = self.get_conversation(conversation_id)
        while latest.ok and latest.execution_status not in {
            "finished",
            "error",
            "stuck",
            "paused",
            "waiting_for_confirmation",
        }:
            if time.monotonic() >= deadline:
                return OpenHandsServiceCall(
                    ok=False,
                    method="GET",
                    path=f"/api/conversations/{conversation_id}",
                    response_json=latest.response_json,
                    error=f"conversation poll timed out after {timeout_seconds:.1f}s",
                )
            time.sleep(max(poll_interval_seconds, 0.1))
            latest = self.get_conversation(conversation_id)
        return latest

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> OpenHandsServiceCall:
        assert self.client is not None
        try:
            response = self.client.request(method, path, json=json, params=params)
            parsed_json: dict[str, Any] = {}
            if response.content:
                try:
                    parsed = response.json()
                    if isinstance(parsed, dict):
                        parsed_json = parsed
                    else:
                        parsed_json = {"data": parsed}
                except ValueError:
                    parsed_json = {"data": response.text}
            if response.is_success:
                return OpenHandsServiceCall(
                    ok=True,
                    method=method,
                    path=path,
                    status_code=response.status_code,
                    response_json=parsed_json,
                    response_text=response.text,
                )
            return OpenHandsServiceCall(
                ok=False,
                method=method,
                path=path,
                status_code=response.status_code,
                response_json=parsed_json,
                response_text=response.text,
                error=response.text or f"HTTP {response.status_code}",
            )
        except httpx.HTTPError as exc:
            return OpenHandsServiceCall(ok=False, method=method, path=path, error=str(exc))


def normalize_openhands_model_name(model_name: str, provider_name: str | None = None) -> str:
    """Convert AutoWeave route names into OpenHands/LiteLLM model identifiers."""

    normalized = model_name.strip()
    if "/" in normalized or not normalized:
        return normalized
    if (provider_name or "").strip().lower() == "vertexai":
        return f"vertex_ai/{normalized}"
    return normalized


def resolve_openhands_reasoning_effort(
    *,
    provider_name: str | None,
    runtime_policy: Mapping[str, Any],
) -> str:
    """Choose a safe default reasoning effort for the OpenHands worker path."""

    configured = runtime_policy.get("reasoning_effort")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    if (provider_name or "").strip().lower() == "vertexai":
        return "none"
    return "medium"


def build_openhands_conversation_request(launch_payload: dict[str, Any]) -> dict[str, Any]:
    """Translate an AutoWeave launch payload into the official OpenHands conversation API."""

    prompt = "\n".join(
        line
        for line in (
            f"Task ID: {launch_payload.get('task_id', '')}",
            f"Task Attempt ID: {launch_payload.get('task_attempt_id', '')}",
            f"Role: {launch_payload.get('task_role', '')}",
            f"Title: {launch_payload.get('task_title', '')}",
            f"Description: {launch_payload.get('task_description', '')}",
            f"Route reason: {launch_payload.get('route_reason', '')}",
        )
        if line and not line.endswith(": ")
    )
    runtime_policy = launch_payload.get("runtime_policy", {})
    workspace_path = str(launch_payload.get("workspace_path", "")).strip()
    return {
        "workspace": {
            "kind": "LocalWorkspace",
            "working_dir": workspace_path,
        },
        "initial_message": {
            "role": "user",
            "run": bool(launch_payload.get("auto_run", True)),
            "content": [
                {
                    "type": "text",
                    "text": prompt or "Execute the assigned AutoWeave task.",
                }
            ],
        },
        "agent": {
            "kind": "Agent",
            "llm": {
                "model": normalize_openhands_model_name(
                    str(launch_payload.get("model_name", "")),
                    str(launch_payload.get("provider_name", "")),
                ),
                "reasoning_effort": resolve_openhands_reasoning_effort(
                    provider_name=str(launch_payload.get("provider_name", "")),
                    runtime_policy=runtime_policy if isinstance(runtime_policy, Mapping) else {},
                ),
            },
            "tools": [
                {"name": "terminal", "params": {}},
                {"name": "file_editor", "params": {}},
                {"name": "task_tracker", "params": {}},
            ],
            "system_prompt_kwargs": {"cli_mode": True},
        },
    }


@dataclass(slots=True, frozen=True)
class WorkspaceReservation:
    """Workspace allocation result for a task attempt."""

    attempt_id: str
    workspace_path: Path
    sandbox_id: str
    resumed_from_attempt_id: str | None = None
    reused_existing_workspace: bool = False


@dataclass(slots=True)
class WorkspacePolicy:
    """Encode the one-isolated-worktree-per-attempt default."""

    root_dir: Path = field(default_factory=lambda: Path("workspaces"))
    isolate_per_attempt: bool = True
    reuse_on_resume: bool = True

    def workspace_path_for_attempt(self, attempt_id: str) -> Path:
        safe_attempt_id = attempt_id.replace("/", "_")
        if self.isolate_per_attempt:
            return self.root_dir / safe_attempt_id
        return self.root_dir

    def reserve(self, *, attempt_id: str, resumed_from_attempt_id: str | None = None) -> WorkspaceReservation:
        workspace_path = self.workspace_path_for_attempt(attempt_id)
        workspace_path.mkdir(parents=True, exist_ok=True)
        return WorkspaceReservation(
            attempt_id=attempt_id,
            workspace_path=workspace_path,
            sandbox_id=f"sandbox-{attempt_id}",
            resumed_from_attempt_id=resumed_from_attempt_id if self.reuse_on_resume else None,
            reused_existing_workspace=bool(resumed_from_attempt_id and self.reuse_on_resume),
        )


@dataclass(slots=True)
class OpenHandsRemoteWorkerAdapter:
    """Scaffold for the OpenHands agent-server remote-worker path."""

    vertex_config: VertexConfig
    workspace_policy: WorkspacePolicy = field(default_factory=WorkspacePolicy)
    service_account_file: str | Path = ""

    def compile_launch_payload(
        self,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        route_reason: str,
        route_model_name: str,
        runtime_policy: dict[str, Any],
    ) -> dict[str, Any]:
        from autoweave.compiler.openhands import OpenHandsConfigCompiler

        compiler = OpenHandsConfigCompiler(
            vertex_config=self.vertex_config,
            service_account_file=self.service_account_file,
            workspace_policy=self.workspace_policy,
        )
        route = ModelRouteRecord(
            workflow_run_id=task.workflow_run_id,
            task_id=task.id,
            task_attempt_id=attempt.id,
            provider_name=self.vertex_config.provider_name,
            model_name=route_model_name,
            route_reason=route_reason,
            estimated_cost_class=str(runtime_policy.get("cost_class", "balanced")),
        )
        return compiler.compile_attempt_config(
            task=task,
            attempt=attempt,
            route=route,
            runtime_policy=runtime_policy,
        )

    def bootstrap_attempt(
        self,
        client: OpenHandsAgentServerClient,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        route_reason: str,
        route_model_name: str,
        runtime_policy: dict[str, Any],
    ) -> OpenHandsServiceCall:
        launch_payload = self.compile_launch_payload(
            task=task,
            attempt=attempt,
            route_reason=route_reason,
            route_model_name=route_model_name,
            runtime_policy=runtime_policy,
        )
        return client.bootstrap_attempt(launch_payload)

    def reserve_workspace(
        self,
        *,
        attempt: TaskAttemptRecord,
        resumed_from_attempt_id: str | None = None,
    ) -> WorkspaceReservation:
        return self.workspace_policy.reserve(
            attempt_id=attempt.id,
            resumed_from_attempt_id=resumed_from_attempt_id,
        )
