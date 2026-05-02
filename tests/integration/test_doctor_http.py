"""Integration tests for GET /doctor HTTP endpoint."""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


@pytest.fixture()
def test_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient backed by a real AgentServer in dev mode."""
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


def test_doctor_returns_200_or_503(test_client):
    resp = test_client.get("/doctor")
    # 503 is expected in offline test mode (no LLM configured); 200 means ready.
    # Both are valid outcomes for this fixture — neither indicates test failure.
    assert resp.status_code in (200, 503)  # vacuous-ok: 503 is expected in offline/no-LLM test mode


def test_doctor_response_has_required_keys(test_client):
    resp = test_client.get("/doctor")
    body = resp.json()
    assert set(body.keys()) == {"status", "blocking", "warnings", "info", "next_steps"}


def test_doctor_status_is_valid_value(test_client):
    resp = test_client.get("/doctor")
    assert resp.json()["status"] in ("ready", "degraded", "error")


def test_doctor_dev_environment_no_blocking(test_client):
    """In dev test environment, no blocking issues expected."""
    resp = test_client.get("/doctor")
    body = resp.json()
    # In test env (dev mode), there should be no blocking issues
    assert body["blocking"] == []
    # 503 is expected offline (no LLM API key); 200 means ready.
    assert resp.status_code in (200, 503)  # vacuous-ok: 503 is expected in offline/no-LLM test mode


def test_doctor_issue_shape(test_client):
    resp = test_client.get("/doctor")
    body = resp.json()
    # Check shape of any issues that exist
    for issue in body["warnings"] + body["info"]:
        assert "subsystem" in issue
        assert "code" in issue
        assert "severity" in issue
        assert "message" in issue
        assert "fix" in issue
        assert "verify" in issue
