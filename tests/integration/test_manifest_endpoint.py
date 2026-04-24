"""Integration: GET /manifest endpoint returns platform capability status.

Uses real AgentServer + Starlette TestClient — no mocks on the SUT.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


@pytest.fixture()
def _server():
    """Shared AgentServer instance with relaxed rate limit for tests."""
    return AgentServer(rate_limit_rps=10000)


@pytest.fixture()
def test_client(_server: AgentServer) -> TestClient:
    """Starlette TestClient wired to the real AgentServer app."""
    return TestClient(_server.app, raise_server_exceptions=False)


def test_manifest_returns_200(test_client: TestClient):
    """GET /manifest must return 200."""
    response = test_client.get("/manifest")
    assert response.status_code == 200


def test_manifest_has_required_keys(test_client: TestClient):
    """GET /manifest response must include platform info keys."""
    response = test_client.get("/manifest")
    assert response.status_code == 200
    data = response.json()
    assert "capabilities" in data
    assert "mcp_servers" in data
    assert "endpoints" in data
    assert "name" in data


def test_manifest_capabilities_is_list(test_client: TestClient):
    """capabilities field must be a list."""
    data = test_client.get("/manifest").json()
    assert isinstance(data["capabilities"], list)


def test_manifest_endpoints_includes_manifest(test_client: TestClient):
    """endpoints list must include GET /manifest."""
    data = test_client.get("/manifest").json()
    assert "GET /manifest" in data["endpoints"]


def test_manifest_name_is_hi_agent(test_client: TestClient):
    """name field must be 'hi-agent'."""
    data = test_client.get("/manifest").json()
    assert data["name"] == "hi-agent"
