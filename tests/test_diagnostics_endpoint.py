"""Tests for the /diagnostics endpoint (P2-10).

Verifies the compact runtime fingerprint returns the fields downstream
operators need to self-serve deploy problems without reading server logs.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setenv("HI_AGENT_KERNEL_BASE_URL", "http://127.0.0.1:8400")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from hi_agent.server.app import AgentServer

    server = AgentServer()
    return TestClient(server._app)


def test_diagnostics_returns_core_fields(client) -> None:
    r = client.get("/diagnostics")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "env",
        "runtime_mode",
        "credentials_present",
        "env_surface",
        "resolved_config",
        "kernel_adapter",
    ):
        assert key in body, f"missing {key}"


def test_diagnostics_reports_env_binding(client) -> None:
    body = client.get("/diagnostics").json()
    # P0-1: HI_AGENT_KERNEL_BASE_URL must be reflected in the resolved config.
    assert body["resolved_config"]["kernel_base_url"] == "http://127.0.0.1:8400"
    assert body["env_surface"]["HI_AGENT_KERNEL_BASE_URL"] == "http://127.0.0.1:8400"


def test_diagnostics_reports_credentials_presence_only(client) -> None:
    creds = client.get("/diagnostics").json()["credentials_present"]
    assert creds["OPENAI_API_KEY"] is True
    assert creds["ANTHROPIC_API_KEY"] is False
    # Never leak the actual key value.
    body_str = str(client.get("/diagnostics").json())
    assert "sk-test" not in body_str


def test_diagnostics_kernel_configured_mode(client) -> None:
    ka = client.get("/diagnostics").json()["kernel_adapter"]
    assert ka["configured_mode"] == "http"
    assert ka["configured_base_url"] == "http://127.0.0.1:8400"
    # Lazy: not built until first run.
    assert ka["built"] is False


def test_diagnostics_local_kernel_mode(monkeypatch) -> None:
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setenv("HI_AGENT_KERNEL_BASE_URL", "local")
    from hi_agent.server.app import AgentServer

    c = TestClient(AgentServer()._app)
    ka = c.get("/diagnostics").json()["kernel_adapter"]
    assert ka["configured_mode"] == "local-fsm"
