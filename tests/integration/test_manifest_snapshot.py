"""Manifest shape snapshot tests — HI-W1-D4-001.

Lock the manifest top-level shape so silent drift is caught immediately.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXCLUDED_KEYS = {"timestamp", "run_id", "started_at", "version", "uptime_seconds"}


def get_stable_manifest(client: TestClient) -> dict:
    resp = client.get("/manifest")
    assert resp.status_code == 200
    return {k: v for k, v in resp.json().items() if k not in EXCLUDED_KEYS}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_manifest_shape_contains_required_keys(test_client: TestClient) -> None:
    """Smoke test: manifest contains all required top-level keys."""
    data = test_client.get("/manifest").json()
    required = {
        "runtime_mode",
        "environment",
        "llm_mode",
        "kernel_mode",
        "evolve_policy",
        "provenance_contract_version",
    }
    missing = required - set(data.keys())
    assert not missing, f"Manifest missing required keys: {missing}"


def test_manifest_evolve_policy_shape_locked(test_client: TestClient) -> None:
    """evolve_policy sub-dict shape must not drift."""
    data = test_client.get("/manifest").json()
    ep = data["evolve_policy"]
    assert set(ep.keys()) == {"mode", "effective", "source"}
