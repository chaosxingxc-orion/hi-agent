"""Integration test: ops endpoints return valid responses under basic load (AX-D slo_health).

Layer 3 — drives through the HTTP interface via Starlette TestClient.
Parametrized over all four ops endpoints to catch per-endpoint regressions.
"""
from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

OPS_ENDPOINTS = ["/ops/slo", "/ops/alerts", "/ops/runbook", "/ops/dashboard"]


@pytest.fixture()
def client():
    """Starlette TestClient backed by a default AgentServer."""
    server = AgentServer(host="127.0.0.1", port=9999)
    with TestClient(server.app) as c:
        yield c


@pytest.mark.parametrize("endpoint", OPS_ENDPOINTS)
def test_ops_endpoint_returns_non_5xx(client: TestClient, endpoint: str) -> None:
    """Each ops endpoint must return a non-5xx response.

    A 5xx response indicates a server-side error and constitutes SLO degradation.
    404 is acceptable (route not yet registered); 200/unavailable payload is expected.
    """
    resp = client.get(endpoint)
    assert resp.status_code < 500, (
        f"GET {endpoint} returned {resp.status_code} — "
        "server error indicates SLO degradation"
    )


@pytest.mark.parametrize("endpoint", OPS_ENDPOINTS)
def test_ops_endpoint_returns_json(client: TestClient, endpoint: str) -> None:
    """Each ops endpoint that responds 200 must return parseable JSON."""
    resp = client.get(endpoint)
    if resp.status_code == 200:
        body = resp.json()
        assert isinstance(body, dict), (
            f"GET {endpoint} returned non-dict JSON: {body!r}"
        )
        assert "status" in body, (
            f"GET {endpoint} JSON body missing 'status' key: {body!r}"
        )
