"""Metrics hooks for AutoWeave observability."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MetricSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    value: float
    labels: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class InMemoryMetricsSink:
    """Simple sink that records metrics in memory for tests."""

    def __init__(self) -> None:
        self.samples: list[MetricSample] = []

    def increment(self, name: str, value: float = 1.0, *, labels: dict[str, str] | None = None) -> None:
        self.samples.append(
            MetricSample(name=name, kind="counter", value=value, labels=labels or {})
        )

    def gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        self.samples.append(
            MetricSample(name=name, kind="gauge", value=value, labels=labels or {})
        )

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        self.samples.append(
            MetricSample(name=name, kind="histogram", value=value, labels=labels or {})
        )


class MetricSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counts: dict[str, float] = Field(default_factory=dict)
    labels: dict[str, dict[str, str]] = Field(default_factory=dict)


def snapshot_metrics(samples: list[MetricSample]) -> MetricSnapshot:
    counts: dict[str, float] = defaultdict(float)
    labels: dict[str, dict[str, str]] = {}
    for sample in samples:
        counts[sample.name] += sample.value
        labels[sample.name] = sample.labels
    return MetricSnapshot(counts=dict(counts), labels=labels)

