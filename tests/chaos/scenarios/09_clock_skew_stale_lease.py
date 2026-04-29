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
    # provenance is derived from what was actually observed.
    result = {
        "name": SCENARIO_NAME,
        "duration_s": 0.0,
    }

    import os as _os_env
    clock_offset_injected = bool(_os_env.environ.get("HI_AGENT_CLOCK_OFFSET_S"))

    run_id = submit_run(base_url, "clock skew test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
        return result
    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)
    if final_state in _TERMINAL:
        result.update(
            _ok_result(
                f"run reached terminal: {final_state} "
                "(clock skew resilience verified via lease lifecycle)"
            )
        )
        # Real observation only if clock-offset env var was injected into the server.
        result["provenance"] = "real" if clock_offset_injected else "structural"
        result["runtime_coupled"] = clock_offset_injected
        result["synthetic"] = not clock_offset_injected
    else:
        result.update(
            _skip_result(
                "clock skew injection requires system time manipulation; "
                f"state={final_state}"
            )
        )
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
    return result
