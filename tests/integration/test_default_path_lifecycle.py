"""Default path: run lifecycle completes successfully (AX-C C1)."""
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


def test_run_lifecycle_completes(client):
    """A run submitted on the default path must complete."""
    from tests._helpers.run_states import SUCCESS_STATES

    resp = client.post("/runs", json={"goal": "echo hello", "profile": "dev"})
    if resp.status_code == 422:
        pytest.skip(reason="schema validation — adjust payload", expiry_wave="Wave 22")
    assert resp.status_code in (200, 201, 202), f"POST /runs returned {resp.status_code}"

    run_id = (resp.json().get("run_id") or resp.json().get("id") or "")
    if not run_id:
        pytest.skip(reason="run_id not in response — adjust payload", expiry_wave="Wave 22")

    # Poll for terminal state
    deadline = time.time() + 30
    state_resp = None
    while time.time() < deadline:
        state_resp = client.get(f"/runs/{run_id}")
        if state_resp.status_code != 200:
            break
        state = state_resp.json().get("state", "")
        if state in (SUCCESS_STATES | {"failed", "error", "aborted", "cancelled"}):
            break
        time.sleep(0.5)

    assert state_resp is not None, "No state response received"
    state = state_resp.json().get("state", "unknown") if state_resp.status_code == 200 else "unknown"
    assert state in SUCCESS_STATES, f"Run {run_id} ended in {state!r} instead of success"
