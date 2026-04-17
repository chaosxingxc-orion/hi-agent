"""Integration tests for /manifest capability_views field — HI-W4-002."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from hi_agent.server.app import AgentServer


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
# Tests
# ---------------------------------------------------------------------------

def test_manifest_has_capability_views_field(test_client):
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    body = resp.json()
    assert "capability_views" in body


def test_manifest_retains_old_capabilities_field(test_client):
    """Backward compat: old capabilities list[str] must still be present."""
    resp = test_client.get("/manifest")
    body = resp.json()
    assert "capabilities" in body
    assert isinstance(body["capabilities"], list)


def test_manifest_capability_contract_version(test_client):
    resp = test_client.get("/manifest")
    assert resp.json().get("capability_contract_version") == "2026-04-17"


def test_capability_views_items_have_correct_shape(test_client):
    resp = test_client.get("/manifest")
    views = resp.json()["capability_views"]
    for view in views:
        assert "name" in view
        assert "status" in view
        assert view["status"] in ("available", "unavailable", "not_wired")
        assert "toolset_id" in view
        assert "required_env" in view
        assert isinstance(view["required_env"], list)
        assert "effect_class" in view
        assert "output_budget_tokens" in view
        assert "availability_reason" in view


def test_capability_views_and_capabilities_names_match(test_client):
    resp = test_client.get("/manifest")
    body = resp.json()
    view_names = sorted(v["name"] for v in body["capability_views"])
    cap_names = sorted(body["capabilities"])
    assert view_names == cap_names
