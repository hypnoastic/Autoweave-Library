"""Coordination primitives for leases and idempotency."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Generic, TypeVar
from urllib.parse import urlparse


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


Clock = Callable[[], datetime]
T = TypeVar("T")


@dataclass(frozen=True)
class LeaseRecord:
    lease_key: str
    acquired_at: datetime
    expires_at: datetime
    holder: str | None = None

    def is_active(self, now: datetime) -> bool:
        return now < self.expires_at


@dataclass(frozen=True)
class IdempotencyRecord(Generic[T]):
    action_key: str
    claimed_at: datetime
    expires_at: datetime
    value: T | None = None

    def is_active(self, now: datetime) -> bool:
        return now < self.expires_at


class RedisProtocolError(RuntimeError):
    """Raised when the Redis wire protocol returns an unexpected frame."""


class RedisClient:
    """Minimal synchronous Redis client that speaks RESP over a socket.

    The project only needs a small command surface for leases and idempotency.
    Using a local client keeps the runtime free of extra Python dependencies
    while still talking to the Dockerized Redis service.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._parsed = urlparse(url)
        self.host = self._parsed.hostname or "127.0.0.1"
        self.port = self._parsed.port or 6379
        self.database = int(self._parsed.path.lstrip("/") or "0")
        self.username = self._parsed.username
        self.password = self._parsed.password

    def ping(self) -> bool:
        return self.execute("PING") == "PONG"

    def get(self, key: str) -> str | None:
        response = self.execute("GET", key)
        return None if response is None else str(response)

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        xx: bool = False,
        ex: int | None = None,
        px: int | None = None,
    ) -> bool:
        command: list[Any] = ["SET", key, value]
        if nx:
            command.append("NX")
        if xx:
            command.append("XX")
        if ex is not None:
            command.extend(["EX", str(int(ex))])
        if px is not None:
            command.extend(["PX", str(int(px))])
        response = self.execute(*command)
        return response == "OK"

    def expire(self, key: str, ttl_seconds: int) -> bool:
        return int(self.execute("EXPIRE", key, str(int(ttl_seconds)))) == 1

    def delete(self, key: str) -> int:
        return int(self.execute("DEL", key))

    def execute(self, *parts: Any) -> Any:
        with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
            sock.settimeout(self.timeout_seconds)
            if self.password is not None or self.username is not None:
                auth_parts = ["AUTH"]
                if self.username:
                    auth_parts.append(self.username)
                if self.password is not None:
                    auth_parts.append(self.password)
                self._write(sock, self._encode(auth_parts))
                self._read(sock)
            if self.database:
                self._write(sock, self._encode(("SELECT", str(self.database))))
                self._read(sock)
            payload = self._encode(parts)
            self._write(sock, payload)
            return self._read(sock)

    def _write(self, sock: socket.socket, payload: bytes) -> None:
        sock.sendall(payload)

    def _read(self, sock: socket.socket) -> Any:
        def readline() -> bytes:
            chunks = bytearray()
            while True:
                char = sock.recv(1)
                if not char:
                    raise RedisProtocolError("unexpected EOF from Redis")
                chunks += char
                if chunks.endswith(b"\r\n"):
                    return bytes(chunks[:-2])

        prefix = sock.recv(1)
        if not prefix:
            raise RedisProtocolError("unexpected EOF from Redis")
        if prefix == b"+":
            return readline().decode("utf-8")
        if prefix == b"-":
            raise RedisProtocolError(readline().decode("utf-8"))
        if prefix == b":":
            return int(readline())
        if prefix == b"$":
            size = int(readline())
            if size == -1:
                return None
            data = bytearray()
            while len(data) < size + 2:
                chunk = sock.recv(size + 2 - len(data))
                if not chunk:
                    raise RedisProtocolError("unexpected EOF while reading bulk string")
                data.extend(chunk)
            return bytes(data[:-2]).decode("utf-8")
        if prefix == b"*":
            length = int(readline())
            if length == -1:
                return None
            return [self._read(sock) for _ in range(length)]
        raise RedisProtocolError(f"unsupported Redis frame: {prefix!r}")

    def _encode(self, parts: tuple[Any, ...] | list[Any]) -> bytes:
        payload = bytearray()
        payload.extend(f"*{len(parts)}\r\n".encode("utf-8"))
        for part in parts:
            encoded = str(part).encode("utf-8")
            payload.extend(f"${len(encoded)}\r\n".encode("utf-8"))
            payload.extend(encoded)
            payload.extend(b"\r\n")
        return bytes(payload)


class RedisLeaseManager:
    """Lease manager backed by Redis key TTLs."""

    def __init__(self, *, client: RedisClient) -> None:
        self._client = client

    def acquire(self, lease_key: str, ttl_seconds: int) -> bool:
        record = LeaseRecord(
            lease_key=lease_key,
            acquired_at=utc_now(),
            expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        )
        return self._client.set(lease_key, json.dumps(record.__dict__, default=str), nx=True, ex=ttl_seconds)

    def heartbeat(self, lease_key: str, ttl_seconds: int) -> None:
        raw = self._client.get(lease_key)
        if raw is None:
            raise KeyError(f"lease {lease_key!r} is not active")
        payload = json.loads(raw)
        payload["expires_at"] = (utc_now() + timedelta(seconds=ttl_seconds)).isoformat()
        if not self._client.set(lease_key, json.dumps(payload, sort_keys=True), xx=True, ex=ttl_seconds):
            raise KeyError(f"lease {lease_key!r} is not active")

    def release(self, lease_key: str) -> None:
        self._client.delete(lease_key)

    def get(self, lease_key: str) -> LeaseRecord | None:
        raw = self._client.get(lease_key)
        if raw is None:
            return None
        payload = json.loads(raw)
        return LeaseRecord(
            lease_key=payload["lease_key"],
            acquired_at=datetime.fromisoformat(payload["acquired_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            holder=payload.get("holder"),
        )

    def reap_expired(self) -> list[str]:
        return []


class RedisIdempotencyStore(Generic[T]):
    """Idempotency window backed by Redis key TTLs."""

    def __init__(self, *, client: RedisClient) -> None:
        self._client = client

    def claim(self, action_key: str, ttl_seconds: int, value: T | None = None) -> bool:
        payload = IdempotencyRecord(
            action_key=action_key,
            claimed_at=utc_now(),
            expires_at=utc_now() + timedelta(seconds=ttl_seconds),
            value=value,
        )
        return self._client.set(action_key, json.dumps(payload.__dict__, default=str), nx=True, ex=ttl_seconds)

    def get(self, action_key: str) -> IdempotencyRecord[T] | None:
        raw = self._client.get(action_key)
        if raw is None:
            return None
        payload = json.loads(raw)
        return IdempotencyRecord(
            action_key=payload["action_key"],
            claimed_at=datetime.fromisoformat(payload["claimed_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            value=payload.get("value"),
        )

    def release(self, action_key: str) -> None:
        self._client.delete(action_key)

    def reap_expired(self) -> list[str]:
        return []


class InMemoryLeaseManager:
    """Lease manager with TTL-based recovery semantics."""

    def __init__(self, *, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._leases: dict[str, LeaseRecord] = {}

    def acquire(self, lease_key: str, ttl_seconds: int) -> bool:
        now = self._clock()
        current = self._leases.get(lease_key)
        if current is not None and current.is_active(now):
            return False
        self._leases[lease_key] = LeaseRecord(
            lease_key=lease_key,
            acquired_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        return True

    def heartbeat(self, lease_key: str, ttl_seconds: int) -> None:
        now = self._clock()
        current = self._leases.get(lease_key)
        if current is None or not current.is_active(now):
            raise KeyError(f"lease {lease_key!r} is not active")
        self._leases[lease_key] = LeaseRecord(
            lease_key=lease_key,
            acquired_at=current.acquired_at,
            expires_at=now + timedelta(seconds=ttl_seconds),
            holder=current.holder,
        )

    def release(self, lease_key: str) -> None:
        self._leases.pop(lease_key, None)

    def get(self, lease_key: str) -> LeaseRecord | None:
        record = self._leases.get(lease_key)
        if record is None:
            return None
        if not record.is_active(self._clock()):
            return None
        return record

    def reap_expired(self) -> list[str]:
        now = self._clock()
        expired = [key for key, record in self._leases.items() if not record.is_active(now)]
        for key in expired:
            self._leases.pop(key, None)
        return expired


class InMemoryIdempotencyStore(Generic[T]):
    """Minimal idempotency window for duplicate Celery deliveries."""

    def __init__(self, *, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._records: dict[str, IdempotencyRecord[T]] = {}

    def claim(self, action_key: str, ttl_seconds: int, value: T | None = None) -> bool:
        now = self._clock()
        current = self._records.get(action_key)
        if current is not None and current.is_active(now):
            return False
        self._records[action_key] = IdempotencyRecord(
            action_key=action_key,
            claimed_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            value=value,
        )
        return True

    def get(self, action_key: str) -> IdempotencyRecord[T] | None:
        record = self._records.get(action_key)
        if record is None or not record.is_active(self._clock()):
            return None
        return record

    def release(self, action_key: str) -> None:
        self._records.pop(action_key, None)

    def reap_expired(self) -> list[str]:
        now = self._clock()
        expired = [key for key, record in self._records.items() if not record.is_active(now)]
        for key in expired:
            self._records.pop(key, None)
        return expired
