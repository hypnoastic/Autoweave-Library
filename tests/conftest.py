from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to avoid warnings."""
    config.addinivalue_line("markers", "integration: mark test as requiring external services (Redis, Postgres)")
    config.addinivalue_line("markers", "ui: mark test as a Playwright UI test")
    config.addinivalue_line("markers", "slow: mark test as slow-running")


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture to ensure tests run with isolated settings."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/15")
    monkeypatch.setenv("VERTEXAI_PROJECT", "test-project")
    monkeypatch.setenv("OPENHANDS_AGENT_SERVER_BASE_URL", "http://localhost:8000")
