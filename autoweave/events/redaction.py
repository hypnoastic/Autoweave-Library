"""Payload redaction helpers for persisted/exported events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REDACTED_VALUE = "[REDACTED]"

SECRET_KEY_MARKERS = (
    "secret",
    "token",
    "password",
    "passwd",
    "private_key",
    "api_key",
    "apikey",
    "access_key",
    "credential",
    "auth",
    "bearer",
)


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def redact_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and is_secret_key(key):
        return REDACTED_VALUE

    if isinstance(value, Mapping):
        return {item_key: redact_value(item_value, key=item_key) for item_key, item_value in value.items()}

    if isinstance(value, list):
        return [redact_value(item, key=key) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_value(item, key=key) for item in value)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_value(item, key=key) for item in value]

    return value


def redact_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    return {
        key: redact_value(value, key=key)
        for key, value in payload.items()
    }

