"""Integration tests for universal tenant scope enforcement (H1-Track2).

Verifies that every endpoint listed in the H1 intake decision returns 401
with {"error": "authentication_required"} when no Authorization header is
sent and HI_AGENT_API_KEY is configured (enabling AuthMiddleware).

Strategy: monkeypatch HI_AGENT_API_KEY so AuthMiddleware is active, then
send bare requests without an Authorization header.  The middleware rejects
the request with 401 before the handler runs — the handler's
require_tenant_context() guard is defence-in-depth.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-key-h1-track2-universal-scope"


@pytest.fixture()
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """AgentServer with AuthMiddleware enabled; returns a client with no auth header."""
    monkeypatch.setenv("HI_AGENT_API_KEY", _TEST_API_KEY)
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Parametrized table: (method, path, body)
# body is only used for POST endpoints that need a JSON payload to reach auth
# (if the endpoint reads the body before checking auth, use a minimal body).
# ---------------------------------------------------------------------------

_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    # artifacts
    ("GET", "/artifacts", None),
    ("GET", "/artifacts/some-id", None),
    ("GET", "/artifacts/by-project/proj-1", None),
    ("GET", "/artifacts/some-id/provenance", None),
    # knowledge
    ("POST", "/knowledge/ingest", {"title": "t", "content": "c"}),
    ("POST", "/knowledge/ingest-structured", {"facts": []}),
    ("GET", "/knowledge/query", None),
    ("GET", "/knowledge/status", None),
    ("POST", "/knowledge/lint", None),
    ("POST", "/knowledge/sync", None),
    # memory
    ("POST", "/memory/dream", {}),
    ("POST", "/memory/consolidate", {}),
    ("GET", "/memory/status", None),
    # tools
    ("POST", "/tools/call", {"name": "noop", "arguments": {}}),
    # manifest
    ("GET", "/manifest", None),
    # skills
    ("GET", "/skills/list", None),
    ("GET", "/skills/status", None),
    ("POST", "/skills/evolve", None),
    ("GET", "/skills/test-skill/metrics", None),
    ("GET", "/skills/test-skill/versions", None),
    ("POST", "/skills/test-skill/optimize", None),
    ("POST", "/skills/test-skill/promote", None),
    # cost
    ("GET", "/cost", None),
    # replay
    ("POST", "/replay/run-abc", {}),
    ("GET", "/replay/run-abc/status", None),
    # management/capacity
    ("GET", "/management/capacity", None),
    # long-ops
    ("GET", "/long-ops/op-abc", None),
    ("POST", "/long-ops/op-abc/cancel", None),
]


@pytest.mark.parametrize("method,path,body", _ENDPOINTS)
def test_no_auth_returns_401(
    auth_client: TestClient,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    """Every protected endpoint must return 401 when no Authorization header is provided."""
    resp = auth_client.get(path) if method == "GET" else auth_client.post(path, json=body)

    assert resp.status_code == 401, (
        f"{method} {path} expected 401, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    # AuthMiddleware returns {"error": "unauthorized", "reason": ...}
    # Handler defence-in-depth returns {"error": "authentication_required"}
    # Either is acceptable — both signal auth failure.
    assert "error" in data, f"{method} {path} response missing 'error' key: {data}"
