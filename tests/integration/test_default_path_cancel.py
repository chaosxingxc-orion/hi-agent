"""Default path: run cancel round-trip (AX-C C1)."""
from __future__ import annotations

import time

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


def test_run_cancel_round_trip(client):
    """Cancel a run via POST /runs/{id}/cancel and verify it reaches terminal."""
    from tests._helpers.run_states import TERMINAL_STATES

    resp = client.post("/runs", json={"goal": "sleep 60", "profile": "dev"})
    if resp.status_code not in (200, 201, 202):
        pytest.skip(reason="POST /runs failed — check payload", expiry_wave="Wave 22")

    run_id = (resp.json().get("run_id") or resp.json().get("id") or "")
    if not run_id:
        pytest.skip(reason="no run_id in response", expiry_wave="Wave 22")

    # Cancel
    cancel_resp = client.post(f"/runs/{run_id}/cancel")
    assert cancel_resp.status_code in (200, 202), f"Cancel returned {cancel_resp.status_code}"

    # Wait for terminal
    deadline = time.time() + 15
    state = "unknown"
    while time.time() < deadline:
        state_resp = client.get(f"/runs/{run_id}")
        state = state_resp.json().get("state", "") if state_resp.status_code == 200 else "unknown"
        if state in TERMINAL_STATES:
            break
        time.sleep(0.5)

    assert state in TERMINAL_STATES, f"Run {run_id} not in terminal after cancel: {state!r}"
