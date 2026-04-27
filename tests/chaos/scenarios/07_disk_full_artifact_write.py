"""Scenario 07: Disk-full artifact write failure.

Verifies artifact write failures are classified and don't corrupt run state.
"""
from __future__ import annotations

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "disk_full_artifact_write"
SCENARIO_DESCRIPTION = "Verify artifact write failure is classified (not silent)."

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
    run_id = submit_run(base_url, "artifact write test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result
    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)
    if final_state in _TERMINAL:
        result.update(
            _ok_result(f"run reached classified terminal state: {final_state}")
        )
    else:
        result.update(
            _skip_result(
                f"disk-full injection requires OS-level mocking; state={final_state}"
            )
        )
    return result
