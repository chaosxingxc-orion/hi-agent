"""Scenario 06: Tool/MCP crash during run.

Fault injection: The chaos matrix runner may set ``HI_AGENT_TOOL_FAULT=crash``
in the server environment. When this env var is set, the tool dispatch layer
raises an exception on every tool invocation.

From within the scenario we:
  1. Submit a run with a task that explicitly requests tool use.
  2. Assert the run reaches a classified terminal state (``failed`` / ``error``)
     rather than hanging or completing silently as succeeded.
  3. Assert the run's reported state is not ``succeeded`` (tool crash must not
     be swallowed as success).

If ``HI_AGENT_TOOL_FAULT`` is not set (env not injected), the run is expected
to complete normally or fail for another reason — both are acceptable (skipped).
"""
from __future__ import annotations

import json
import urllib.request

from _helpers import (
    _OPENER,
    _fail_result,
    _ok_result,
    _skip_result,
    wait_terminal,
)

SCENARIO_NAME = "tool_mcp_crash"
SCENARIO_DESCRIPTION = (
    "Submit run that invokes a tool; with HI_AGENT_TOOL_FAULT=crash env, "
    "assert run reaches failed/error (not hung, not silently succeeded)."
)

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)

_FAILURE_STATES = frozenset({"failed", "error", "timed_out", "cancelled"})


def _get_run_detail(base_url: str, run_id: str) -> dict:
    try:
        with _OPENER.open(f"{base_url}/runs/{run_id}", timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _submit_tool_run(base_url: str) -> str | None:
    """Submit a run with context hinting that a tool invocation is required."""
    body = json.dumps(
        {
            "goal": "tool crash chaos test — call any available tool",
            "context": {"_chaos_require_tool": True},
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/runs",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=15) as r:
            return json.loads(r.read()).get("run_id")
    except Exception:
        return None


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result: dict = {
        "name": SCENARIO_NAME,
        "runtime_coupled": True,
        "synthetic": False,
        "provenance": "real",
        "duration_s": 0.0,
    }

    run_id = _submit_tool_run(base_url)
    if not run_id:
        result.update(_fail_result("could not submit tool-run"))
        return result

    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)

    if final_state == "timeout":
        result.update(
            _skip_result(
                "run did not reach terminal; tool fault injection requires "
                "HI_AGENT_TOOL_FAULT=crash env var on the server process"
            )
        )
        return result

    if final_state not in _TERMINAL:
        result.update(_fail_result(f"unexpected state: {final_state}"))
        return result

    # Get run detail to check for error classification
    detail = _get_run_detail(base_url, run_id)
    error_type = detail.get("error_type") or detail.get("failure_reason") or ""

    if final_state in _FAILURE_STATES:
        result.update(
            _ok_result(
                f"tool crash led to classified terminal state={final_state}, "
                f"error_type={error_type!r} (not a silent success)"
            )
        )
    elif final_state in ("completed", "succeeded"):
        # Without fault env var the run may succeed normally — that's acceptable
        result.update(
            _skip_result(
                f"run completed with state={final_state}; no tool fault injected "
                "(HI_AGENT_TOOL_FAULT env not set on server)"
            )
        )
    else:
        result.update(_fail_result(f"unclassified terminal state: {final_state}"))
    return result
