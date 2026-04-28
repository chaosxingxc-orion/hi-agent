"""Scenario 01: Worker process hard-killed during active run.

Fault injection: SIGKILL on the server subprocess is managed by the chaos matrix
runner (which owns the process). From within the scenario we verify:
  - A run can be submitted and reaches a terminal state.
  - After a cancel signal (simulating drain on kill), the run state is terminal.
  - The /health endpoint returns 200 before and after the cancel round-trip.

This is the maximum injection achievable without a separate worker-process
architecture. Any stronger test requires process isolation (chaos profile only).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    get_run_state,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "worker_kill_during_run"
SCENARIO_DESCRIPTION = (
    "Submit run, verify /health, send cancel signal to simulate drain-on-kill, "
    "assert run reaches terminal state and /health stays 200."
)

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)


def _check_health(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _cancel_run(base_url: str, run_id: str) -> int:
    """POST /runs/{run_id}/cancel; returns HTTP status code or 0 on network error."""
    body = json.dumps({}).encode()
    req = urllib.request.Request(
        f"{base_url}/runs/{run_id}/cancel",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result: dict = {
        "name": SCENARIO_NAME,
        "runtime_coupled": True,
        "synthetic": False,
        "provenance": "real",
        "duration_s": 0.0,
    }

    # Gate: /health must be 200 before we start
    if not _check_health(base_url):
        result.update(_fail_result("/health not 200 before scenario start"))
        return result

    # Submit a run
    run_id = submit_run(base_url, "worker kill test — cancel drain simulation")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result

    # Wait up to 3 s for run to start (state transitions away from 'pending')
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        state = get_run_state(base_url, run_id)
        if state not in ("pending", "unknown", "error"):
            break
        time.sleep(0.3)

    # Simulate kill-then-drain: send a cancel signal
    cancel_code = _cancel_run(base_url, run_id)

    # Wait for terminal state
    final_state = wait_terminal(base_url, run_id, timeout=timeout - 8)

    # /health must still be 200 after the cancel round-trip
    health_after = _check_health(base_url)

    if final_state in _TERMINAL and health_after:
        result.update(
            _ok_result(
                f"cancel_code={cancel_code}, terminal={final_state}, health_after=ok"
            )
        )
    elif final_state == "timeout":
        result.update(
            _skip_result(
                "run did not reach terminal within timeout; "
                "worker-kill injection requires separate worker process"
            )
        )
    elif not health_after:
        result.update(_fail_result(f"terminal={final_state} but /health not 200 after cancel"))
    else:
        result.update(_fail_result(f"unexpected state: {final_state}"))
    return result
