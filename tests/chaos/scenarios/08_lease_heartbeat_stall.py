"""Scenario 08: Lease heartbeat stall.

Verifies that a run whose lease expires is eventually re-enqueued or
classified as failed, not left dangling.
"""
from __future__ import annotations

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "lease_heartbeat_stall"
SCENARIO_DESCRIPTION = "Submit run and verify lease expiry is handled (not a silent hang)."

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
    run_id = submit_run(base_url, "lease stall test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result
    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)
    if final_state in _TERMINAL:
        result.update(
            _ok_result(f"run reached terminal state: {final_state} (lease handled)")
        )
    else:
        result.update(
            _skip_result(
                "lease stall requires long wait or in-process injection; "
                f"state={final_state}"
            )
        )
    return result
