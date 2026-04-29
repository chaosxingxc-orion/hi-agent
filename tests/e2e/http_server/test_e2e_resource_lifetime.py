"""E2E: three sequential runs must reuse the same gateway — no Event loop errors.

Layer-3 E2E tests per Rule 4 and Rule 5 (async resource lifetime). Drive
through the public HTTP interface.
All tests skip when no server is reachable (see conftest.py).
"""

from __future__ import annotations

import time

import pytest

from tests._helpers.run_states import TERMINAL_STATES

pytestmark = [pytest.mark.e2e, pytest.mark.network]

_TERMINAL_STATES = TERMINAL_STATES
_POLL_INTERVAL_S = 2
_POLL_MAX_ROUNDS = 10


def _wait_for_terminal(client, run_id: str) -> str:
    """Poll until terminal state, return final state or 'timeout'."""
    for _ in range(_POLL_MAX_ROUNDS):
        r = client.get(f"/runs/{run_id}")
        if r.status_code == 200:
            state = r.json().get("state")
            if state in _TERMINAL_STATES:
                return state
        time.sleep(_POLL_INTERVAL_S)
    return "timeout"


def test_three_sequential_runs_no_event_loop_error(e2e_client):
    """Run 1, 2, 3 back-to-back; each must respond 200 or 422 — no 500.

    A 500 with 'Event loop is closed' indicates Rule 5 violation (async
    resource shared across asyncio.run() calls).
    """
    for i in range(3):
        resp = e2e_client.post(
            "/runs",
            json={"goal": f"sequential test run {i}", "profile_id": "default"},
        )
        assert resp.status_code in (200, 422), (
            f"Run {i} returned unexpected status {resp.status_code}: {resp.text}"
        )
        if resp.status_code == 200:
            run_id = resp.json()["run_id"]
            _wait_for_terminal(e2e_client, run_id)


def test_health_still_200_after_runs(e2e_client):
    """GET /health must return 200 after sequential runs (no resource leak)."""
    for i in range(2):
        e2e_client.post(
            "/runs",
            json={"goal": f"pre-health-check run {i}", "profile_id": "default"},
        )

    resp = e2e_client.get("/health")
    assert resp.status_code == 200, (
        f"Server health degraded after sequential runs: {resp.status_code}"
    )
