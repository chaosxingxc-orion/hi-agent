"""Integration tests for /ops/slo, /ops/alerts, /ops/runbook, /ops/dashboard routes.

Layer 2 integration: real AgentServer + Starlette TestClient; no mocks on
the subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


@pytest.fixture()
def client():
    """Starlette TestClient backed by a default AgentServer."""
    server = AgentServer(host="127.0.0.1", port=9999)
    with TestClient(server.app) as c:
        yield c


class TestOpsSloRoute:
    """GET /ops/slo."""

    def test_returns_200(self, client: TestClient) -> None:
        """Route must return HTTP 200 regardless of whether metrics exist."""
        resp = client.get("/ops/slo")
        assert resp.status_code == 200

    def test_body_has_status_key(self, client: TestClient) -> None:
        """Response body must contain a 'status' key."""
        body = client.get("/ops/slo").json()
        assert "status" in body
        assert body["status"] in ("ok", "unavailable")


class TestOpsAlertsRoute:
    """GET /ops/alerts."""

    def test_returns_200(self, client: TestClient) -> None:
        """Route must return HTTP 200."""
        resp = client.get("/ops/alerts")
        assert resp.status_code == 200

    def test_body_has_status_and_data(self, client: TestClient) -> None:
        """Response body must contain 'status' and 'data' keys."""
        body = client.get("/ops/alerts").json()
        assert "status" in body
        assert body["status"] in ("ok", "unavailable")
        if body["status"] == "ok":
            assert isinstance(body["data"], list)


class TestOpsRunbookRoute:
    """GET /ops/runbook."""

    def test_returns_200(self, client: TestClient) -> None:
        """Route must return HTTP 200."""
        resp = client.get("/ops/runbook")
        assert resp.status_code == 200

    def test_body_has_status_ok_and_data(self, client: TestClient) -> None:
        """Runbook generation is pure; response must be ok with data dict."""
        body = client.get("/ops/runbook").json()
        assert body["status"] == "ok"
        assert isinstance(body["data"], dict)
        assert "steps" in body["data"]

    def test_severity_param_high(self, client: TestClient) -> None:
        """?severity=high must return a runbook with more steps."""
        body = client.get("/ops/runbook?severity=high").json()
        assert body["status"] == "ok"
        assert len(body["data"]["steps"]) >= 3

    def test_invalid_severity_falls_back_to_low(self, client: TestClient) -> None:
        """Unknown severity must not cause a 500; falls back to 'low'."""
        resp = client.get("/ops/runbook?severity=bogus")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"


class TestOpsDashboardRoute:
    """GET /ops/dashboard."""

    def test_returns_200(self, client: TestClient) -> None:
        """Route must return HTTP 200."""
        resp = client.get("/ops/dashboard")
        assert resp.status_code == 200

    def test_body_has_status_and_data(self, client: TestClient) -> None:
        """Response body must contain 'status' and 'data' keys."""
        body = client.get("/ops/dashboard").json()
        assert "status" in body
        assert body["status"] in ("ok", "unavailable")
        if body["status"] == "ok":
            assert "summary" in body["data"]
            assert "status_badge" in body["data"]
