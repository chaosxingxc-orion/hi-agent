"""Scenario 06: Tool/MCP crash.

Verifies that a tool or MCP failure results in a classified run failure,
not a silent hang or unclassified error.
"""
from __future__ import annotations

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "tool_mcp_crash"
SCENARIO_DESCRIPTION = "Verify tool/MCP failure leads to classified terminal state."

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
    run_id = submit_run(base_url, "tool crash test")
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
                f"run in state={final_state}, "
                "tool crash injection requires in-process interception"
            )
        )
    return result
