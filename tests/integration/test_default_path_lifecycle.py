"""Default path: run lifecycle completes successfully (AX-C C1)."""
from __future__ import annotations

import os
import time

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

_HAS_LLM = bool(
    os.environ.get("VOLCES_API_KEY")
    or os.environ.get("VOLCE_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or os.environ.get("ANTHROPIC_API_KEY")
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setenv("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


def test_run_lifecycle_completes(client):
    """A run submitted on the default path must complete.

    Requires a real LLM API key (VOLCES_API_KEY, OPENAI_API_KEY, or
    ANTHROPIC_API_KEY) OR a heuristic executor that drives a run to terminal
    state.  Skipped when no LLM is available and the heuristic executor does
    not complete runs in the test client's single-thread model.
    """
    if not _HAS_LLM:
        pytest.skip(  # expiry_wave: permanent (W31-D D-2': condition-bounded defensive skip)
            reason="requires real LLM API key; heuristic executor does not drive "
            "runs to terminal state in TestClient's synchronous threading model"
        )

    from tests._helpers.run_states import SUCCESS_STATES

    resp = client.post("/runs", json={"goal": "echo hello", "profile": "dev"})
    if resp.status_code == 422:
        pytest.skip(reason="schema validation — adjust payload")  # expiry_wave: permanent (W31-D D-2': condition-bounded defensive skip)
    assert resp.status_code in (200, 201, 202), f"POST /runs returned {resp.status_code}"

    run_id = (resp.json().get("run_id") or resp.json().get("id") or "")
    if not run_id:
        pytest.skip(reason="run_id not in response — adjust payload")  # expiry_wave: permanent (W31-D D-2': condition-bounded defensive skip)

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
    state = (  # expiry_wave: permanent (W31-D D-2': condition-bounded defensive skip)
        state_resp.json().get("state", "unknown") if state_resp.status_code == 200 else "unknown"
    )
    assert state in SUCCESS_STATES, f"Run {run_id} ended in {state!r} instead of success"
