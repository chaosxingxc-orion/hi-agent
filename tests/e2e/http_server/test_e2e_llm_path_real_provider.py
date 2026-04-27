"""E2E: real LLM provider path — requires HI_AGENT_LLM_MODE=real and API keys.

Layer-3 E2E tests per Rule 4 and Rule 8 (operator-shape readiness gate).
These tests are skipped unless HI_AGENT_LLM_MODE=real is set in the
environment, as they make real LLM calls.

Usage:
    HI_AGENT_LLM_MODE=real pytest tests/e2e/http_server/test_e2e_llm_path_real_provider.py
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.external_llm,
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("HI_AGENT_LLM_MODE") != "real",
        reason="Set HI_AGENT_LLM_MODE=real to run real-provider E2E tests",
    ),
]

_TERMINAL_STATES = frozenset({"done", "failed", "cancelled"})
_POLL_INTERVAL_S = 5
_POLL_MAX_ROUNDS = 60  # 60 * 5s = 300s


def test_real_llm_run_completes(e2e_client):
    """POST /runs with a simple goal -> reaches state=done with llm_fallback_count=0.

    This is the Rule 8 gate criterion: sequential real-LLM runs must reach
    done in <= 2 * observed_p95 with llm_fallback_count == 0 in run metadata.
    """
    resp = e2e_client.post(
        "/runs",
        json={"goal": "Say hello in one sentence.", "profile_id": "default"},
    )
    assert resp.status_code == 200, f"POST /runs returned {resp.status_code}: {resp.text}"
    run_id = resp.json()["run_id"]

    for _ in range(_POLL_MAX_ROUNDS):
        r = e2e_client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        data = r.json()
        state = data.get("state")
        if state == "done":
            fallback_count = data.get("llm_fallback_count", 0)
            assert fallback_count == 0, (
                f"Run reached done but llm_fallback_count={fallback_count} != 0 "
                "(Rule 7/Rule 8 violation)"
            )
            return
        if state == "failed":
            pytest.fail(f"Real LLM run {run_id} failed: {data}")
        time.sleep(_POLL_INTERVAL_S)

    pytest.fail(f"Real LLM run {run_id} did not reach done state within 300s")


def test_three_sequential_real_llm_runs(e2e_client):
    """Three back-to-back real LLM runs must all succeed — Rule 8 criterion 3.

    Verifies cross-loop resource stability: run 2 and 3 must reuse the same
    gateway instance as run 1 without 'Event loop is closed' errors.
    """
    run_ids = []

    for i in range(3):
        resp = e2e_client.post(
            "/runs",
            json={"goal": f"Count to {i + 1}.", "profile_id": "default"},
        )
        assert resp.status_code == 200, (
            f"Sequential run {i} returned {resp.status_code}: {resp.text}"
        )
        run_ids.append(resp.json()["run_id"])

    for run_id in run_ids:
        for _ in range(_POLL_MAX_ROUNDS):
            r = e2e_client.get(f"/runs/{run_id}")
            assert r.status_code == 200
            state = r.json().get("state")
            if state in _TERMINAL_STATES:
                assert state == "done", (
                    f"Sequential real LLM run {run_id} ended in state={state}, expected done"
                )
                break
            time.sleep(_POLL_INTERVAL_S)
        else:
            pytest.fail(f"Sequential real LLM run {run_id} did not terminate within 300s")
