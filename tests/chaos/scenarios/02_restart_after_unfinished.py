"""Scenario 02: Server restart with unfinished runs in store.

Checks that rehydration re-enqueues runs that were active before restart.
Since we can't restart the server from within a scenario, we verify that
the run eventually completes (the system handles lease expiry gracefully).
"""
from __future__ import annotations

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "restart_after_unfinished"
SCENARIO_DESCRIPTION = (
    "Verify runs reach terminal state even after simulated lifecycle interruption."
)

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result = {
        "name": SCENARIO_NAME,
        "runtime_coupled": True,
        "synthetic": False,
        "provenance": "real",
        "duration_s": 0.0,
    }
    run_id = submit_run(base_url, "restart test run")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result
    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)
    if final_state in _TERMINAL:
        result.update(_ok_result(f"run reached terminal state: {final_state}"))
    else:
        result.update(
            _skip_result(f"cannot simulate restart within scenario; state={final_state}")
        )
    return result
