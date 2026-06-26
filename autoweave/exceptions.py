"""Shared exception types for AutoWeave."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from typing import Any


class AutoweaveError(Exception):
    """Base error for library-specific failures."""


class ConfigurationError(AutoweaveError):
    """Raised when canonical config or runtime wiring is invalid."""


class StateTransitionError(AutoweaveError):
    """Raised when a state-machine transition is rejected."""


class RuntimeErrorCode(StrEnum):
    """Stable failure codes for runtime and operator-facing surfaces."""

    CONFIGURATION_INVALID = "configuration_invalid"
    AGENT_CATALOG_UNAVAILABLE = "agent_catalog_unavailable"
    WORKFLOW_BLUEPRINT_UNAVAILABLE = "workflow_blueprint_unavailable"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    QUEUE_UNAVAILABLE = "queue_unavailable"
    JOB_EXECUTION_FAILED = "job_execution_failed"
    INVALID_ACTION = "invalid_action"


@dataclass(slots=True, frozen=True)
class RuntimeFailure:
    """Typed runtime failure that can be surfaced through payloads safely."""

    code: RuntimeErrorCode
    message: str
    recoverable: bool = False
    details_json: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "recoverable": self.recoverable,
            "details_json": dict(self.details_json),
        }


class RuntimeOperationError(AutoweaveError):
    """Typed runtime failure that preserves machine-readable failure metadata."""

    def __init__(
        self,
        *,
        code: RuntimeErrorCode,
        message: str,
        recoverable: bool = False,
        details_json: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.details_json = dict(details_json or {})

    @property
    def failure(self) -> RuntimeFailure:
        return RuntimeFailure(
            code=self.code,
            message=self.message,
            recoverable=self.recoverable,
            details_json=self.details_json,
        )
