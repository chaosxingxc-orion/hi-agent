"""E2E: full run lifecycle — start, poll until terminal, cancel.

Layer-3 E2E tests per Rule 4. Drive through the public HTTP interface.
All tests skip when no server is reachable (see conftest.py).
"""

from __future__ import annotations

import os
import time

import pytest

from tests._helpers.run_states import SUCCESS_STATES, TERMINAL_STATES

pytestmark = [pytest.mark.e2e, pytest.mark.network]

_TERMINAL_STATES = TERMINAL_STATES
_POLL_INTERVAL_S = 3
_POLL_MAX_ROUNDS = 40  # 40 * 3s = 120s


@pytest.mark.skipif(
    not os.environ.get("HI_AGENT_LLM_KEY"),
    reason="requires LLM key (HI_AGENT_LLM_KEY); skipped in offline environment",
)
def test_run_reaches_terminal_state(e2e_client):
    """POST /runs -> poll until state == 'done' within 120s.

    A basic lifecycle run with a real LLM key must complete successfully.
    """
    resp = e2e_client.post("/runs", json={"goal": "echo test", "profile_id": "default"})
    assert resp.status_code == 200, (
        f"POST /runs returned {resp.status_code} — server rejected run payload: {resp.text}"
    )
    run_id = resp.json()["run_id"]

    state = None
    for _ in range(_POLL_MAX_ROUNDS):
        r = e2e_client.get(f"/runs/{run_id}")
        assert r.status_code == 200, f"GET /runs/{run_id} returned {r.status_code}"
        state = r.json().get("state")
        if state in _TERMINAL_STATES:
            break
        time.sleep(_POLL_INTERVAL_S)
    else:
        pytest.fail(f"Run {run_id} did not reach a terminal state within 120s")

    assert state in SUCCESS_STATES, (
        f"Run ended in failure state: {state!r}. "
        "A basic lifecycle run must complete successfully, not fail or be cancelled."
    )


def test_cancel_live_run(e2e_client):
    """POST /runs -> cancel within 5s -> 200 response."""
    resp = e2e_client.post(
        "/runs", json={"goal": "long running task sleep 300", "profile_id": "default"}
    )
    if resp.status_code != 200:
        pytest.fail(f"Could not start run: POST /runs returned {resp.status_code}: {resp.text}")
    run_id = resp.json()["run_id"]

    time.sleep(1)
    cancel = e2e_client.post(f"/runs/{run_id}/cancel")
    assert cancel.status_code == 200, (
        f"POST /runs/{run_id}/cancel returned {cancel.status_code}: {cancel.text}"
    )


def test_cancel_unknown_run_returns_404(e2e_client):
    """POST /runs/nonexistent-run-id/cancel must return 404."""
    r = e2e_client.post("/runs/nonexistent-run-id-lifecycle-xyz/cancel")
    assert r.status_code == 404
