"""Common type aliases used across workstreams."""

from __future__ import annotations

from typing import Any, NewType

JsonValue = Any
JsonDict = dict[str, JsonValue]

ProjectId = NewType("ProjectId", str)
WorkflowRunId = NewType("WorkflowRunId", str)
TaskId = NewType("TaskId", str)
TaskAttemptId = NewType("TaskAttemptId", str)
ArtifactId = NewType("ArtifactId", str)
HumanRequestId = NewType("HumanRequestId", str)

PathLike = str
AnyMapping = dict[str, Any]
