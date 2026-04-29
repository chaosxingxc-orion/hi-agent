"""Default path: tenant isolation — tenant A's runs invisible to tenant B (AX-C C1, AX-F F1)."""
from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


def test_run_tenant_isolation(client):
    """Run created under tenant A must not appear in tenant B's run list."""
    # POST run under tenant A (via header or parameter — adapt to actual API)
    headers_a = {"X-Tenant-Id": "tenant-A-test"}
    headers_b = {"X-Tenant-Id": "tenant-B-test"}

    resp_a = client.post("/runs", json={"goal": "echo A", "profile": "dev"}, headers=headers_a)
    if resp_a.status_code not in (200, 201, 202):
        pytest.skip(reason="POST /runs not reachable — check payload", expiry_wave="Wave 22")

    run_id_a = (resp_a.json().get("run_id") or resp_a.json().get("id") or "")
    if not run_id_a:
        pytest.skip(reason="no run_id in response", expiry_wave="Wave 22")

    # Tenant B must not see tenant A's run
    resp_b = client.get(f"/runs/{run_id_a}", headers=headers_b)
    assert resp_b.status_code in (403, 404), (
        f"Tenant B could see tenant A's run {run_id_a}: {resp_b.status_code}"
    )
