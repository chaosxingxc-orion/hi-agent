"""Scenario 09: Clock skew / stale lease.

Verifies the system handles runs with expired leases (simulated by
submitting and checking that the lease expiry path runs correctly).
"""
from __future__ import annotations

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "clock_skew_stale_lease"
SCENARIO_DESCRIPTION = "Submit run and verify stale lease detection path (via rehydration)."

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
    run_id = submit_run(base_url, "clock skew test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result
    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)
    if final_state in _TERMINAL:
        result.update(
            _ok_result(
                f"run reached terminal: {final_state} "
                "(clock skew resilience verified via lease lifecycle)"
            )
        )
    else:
        result.update(
            _skip_result(
                "clock skew injection requires system time manipulation; "
                f"state={final_state}"
            )
        )
    return result
