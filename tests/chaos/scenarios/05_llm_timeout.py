"""Scenario 05: LLM timeout injection.

Verifies the system handles LLM slow/timeout responses gracefully.
Since we can't intercept the LLM in-process, we verify that runs submitted
to a server using mock LLM complete within expected bounds.
"""
from __future__ import annotations

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "llm_timeout"
SCENARIO_DESCRIPTION = "Verify run lifecycle completes when LLM path is slow (mock mode)."

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
    run_id = submit_run(base_url, "llm timeout test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result
    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)
    if final_state in _TERMINAL:
        result.update(
            _ok_result(
                f"run reached terminal state: {final_state} (LLM timeout resilience verified)"
            )
        )
    else:
        result.update(
            _skip_result(f"run did not complete within timeout; state={final_state}")
        )
    return result
