"""Integration tests for operation-driven RBAC/SOC wiring (HI-W1-D5-001).

Exercises the real app routes via HTTP test client.
No internal mocking — production integrity rule applies.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _base_server():
    """Shared AgentServer instance (rate-limit relaxed)."""
    return AgentServer(rate_limit_rps=10000)


@pytest.fixture()
def dev_client(_base_server: AgentServer) -> TestClient:
    """Test client in dev-smoke runtime mode."""
    _base_server.app.state.runtime_mode = "dev-smoke"
    return TestClient(_base_server.app, raise_server_exceptions=False)


@pytest.fixture()
def prod_client(_base_server: AgentServer) -> TestClient:
    """Test client in prod-real runtime mode."""
    _base_server.app.state.runtime_mode = "prod-real"
    return TestClient(_base_server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_prod_skill_promote_without_role_returns_403(prod_client: TestClient):
    """POST /skills/{id}/promote in prod requires approver role (default role is 'submitter')."""
    resp = prod_client.post("/skills/test-skill/promote")
    assert resp.status_code == 403
    body = resp.json()
    detail = body.get("detail", body)
    assert detail.get("error") == "unauthorized"
    assert detail.get("operation") == "skill.promote"
    assert isinstance(detail.get("required_roles"), list)
    assert detail.get("reason") in ("missing_role", "soc_violation")


def test_prod_skill_evolve_without_role_returns_403(prod_client: TestClient):
    """POST /skills/evolve in prod requires approver role (default role is 'submitter')."""
    resp = prod_client.post("/skills/evolve")
    assert resp.status_code == 403
    body = resp.json()
    detail = body.get("detail", body)
    assert detail.get("error") == "unauthorized"
    assert detail.get("operation") == "skill.evolve"
    assert detail.get("reason") in ("missing_role", "soc_violation")


def test_prod_memory_consolidate_without_role_returns_403(prod_client: TestClient):
    """POST /memory/consolidate in prod requires approver role (default role is 'submitter')."""
    resp = prod_client.post("/memory/consolidate")
    assert resp.status_code == 403
    body = resp.json()
    detail = body.get("detail", body)
    assert detail.get("error") == "unauthorized"
    assert detail.get("operation") == "memory.consolidate"
    assert detail.get("reason") in ("missing_role", "soc_violation")


def test_dev_skill_promote_without_role_succeeds(dev_client: TestClient):
    """In dev-smoke, skill.promote bypasses RBAC."""
    resp = dev_client.post("/skills/test-skill/promote")
    # Dev bypass: must NOT be 403
    assert resp.status_code != 403


def test_dev_skill_evolve_without_role_succeeds(dev_client: TestClient):
    """In dev-smoke, skill.evolve bypasses RBAC."""
    resp = dev_client.post("/skills/evolve")
    assert resp.status_code != 403


def test_dev_memory_consolidate_without_role_succeeds(dev_client: TestClient):
    """In dev-smoke, memory.consolidate bypasses RBAC."""
    resp = dev_client.post("/memory/consolidate")
    assert resp.status_code != 403


def test_post_runs_not_protected_in_dev(dev_client: TestClient):
    """POST /runs must NOT require auth (ever)."""
    resp = dev_client.post("/runs", json={"goal": "auth guard smoke"})
    assert resp.status_code not in (401, 403)


def test_post_runs_not_protected_in_prod(prod_client: TestClient):
    """POST /runs must NOT require auth even in prod."""
    resp = prod_client.post("/runs", json={"goal": "auth guard smoke"})
    assert resp.status_code not in (401, 403)
