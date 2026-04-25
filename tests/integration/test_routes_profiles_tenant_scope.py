"""Integration tests for tenant scope enforcement on routes_profiles (H2-Track2).

Verifies that handle_global_l3_summary and handle_global_skills gate behind
require_tenant_context(), returning 401 for unauthenticated callers.

C2 fix: both handlers were public with no require_tenant_context() call,
allowing anonymous callers to read deployment-topology data.

Strategy: monkeypatch HI_AGENT_API_KEY so AuthMiddleware is active, then
send bare requests without an Authorization header.  AuthMiddleware rejects
with 401 before the handler body runs; the handler's require_tenant_context()
guard is defence-in-depth.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-key-h2-track2-profiles-scope"


@pytest.fixture()
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """AgentServer with AuthMiddleware enabled; returns a client with no auth header."""
    monkeypatch.setenv("HI_AGENT_API_KEY", _TEST_API_KEY)
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


@pytest.fixture()
def authed_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """AgentServer with a valid Authorization header pre-set."""
    monkeypatch.setenv("HI_AGENT_API_KEY", _TEST_API_KEY)
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(
        server.app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
    )


# ---------------------------------------------------------------------------
# C2 — unauthenticated requests must be rejected
# ---------------------------------------------------------------------------


def test_global_l3_no_auth_returns_401(auth_client: TestClient) -> None:
    """GET /profiles/hi_agent_global/memory/l3 must return 401 without Authorization."""
    resp = auth_client.get("/profiles/hi_agent_global/memory/l3")
    assert resp.status_code == 401, (
        f"expected 401, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert "error" in data, f"response missing 'error' key: {data}"


def test_global_skills_no_auth_returns_401(auth_client: TestClient) -> None:
    """GET /profiles/hi_agent_global/skills must return 401 without Authorization."""
    resp = auth_client.get("/profiles/hi_agent_global/skills")
    assert resp.status_code == 401, (
        f"expected 401, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert "error" in data, f"response missing 'error' key: {data}"


# ---------------------------------------------------------------------------
# C2 — authenticated requests must not be rejected with 401
# ---------------------------------------------------------------------------


def test_global_l3_with_auth_not_401(authed_client: TestClient) -> None:
    """GET /profiles/hi_agent_global/memory/l3 with valid auth must not return 401."""
    resp = authed_client.get("/profiles/hi_agent_global/memory/l3")
    assert resp.status_code != 401, (
        f"authenticated request unexpectedly got 401: {resp.text}"
    )


def test_global_skills_with_auth_not_401(authed_client: TestClient) -> None:
    """GET /profiles/hi_agent_global/skills with valid auth must not return 401."""
    resp = authed_client.get("/profiles/hi_agent_global/skills")
    assert resp.status_code != 401, (
        f"authenticated request unexpectedly got 401: {resp.text}"
    )
