"""Shared fixtures for agent_server tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def tenant_context() -> dict:
    """Minimal tenant context for tests."""
    return {
        "tenant_id": "test-tenant-001",
        "project_id": "test-project-001",
    }


@pytest.fixture
def workspace_path(tmp_path):
    """Temporary workspace directory for tests."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def session_id() -> str:
    """Stable session ID for tests."""
    return "test-session-001"
