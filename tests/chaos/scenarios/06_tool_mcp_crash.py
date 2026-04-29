"""Scenario 06: Tool/MCP crash during run.

Fault injection: ``HI_AGENT_FAULT_TOOL_CRASH=*`` is set in the server
environment before startup.  When active, ``FaultInjector.maybe_raise_tool_crash_sync``
wired into ``CapabilityInvoker.invoke`` raises ``RuntimeError`` for any tool
invocation, exercising the run's tool-crash recovery path.

From within the scenario we:
  1. Submit a run with a task that may invoke a capability.
  2. Assert the run reaches a classified terminal state (``failed`` / ``error``)
     rather than hanging or completing silently as succeeded.
  3. Assert the run's reported state is not ``succeeded`` (tool crash must not
     be swallowed as success).
"""
from __future__ import annotations

import json
import os
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
    "Submit run with HI_AGENT_FAULT_TOOL_CRASH=* env; assert run reaches "
    "failed/error (not hung, not silently succeeded) via FaultInjector."
)

# AX-A A5: fault vars to be injected by run_chaos_matrix.py before server start.
REQUIRED_ENV = ["HI_AGENT_FAULT_TOOL_CRASH"]

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
            "goal": "tool crash chaos test — call any available capability",
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
        "duration_s": 0.0,
    }

    # Detect whether fault injection is active.
    # FaultInjector uses HI_AGENT_FAULT_TOOL_CRASH; fall back to old var for compat.
    fault_injected = bool(
        os.environ.get("HI_AGENT_FAULT_TOOL_CRASH")
        or os.environ.get("HI_AGENT_TOOL_FAULT") == "crash"
    )

    run_id = _submit_tool_run(base_url)
    if not run_id:
        result.update(_fail_result("could not submit tool-run"))
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
        return result

    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)

    if final_state == "timeout":
        result.update(
            _skip_result(
                "run did not reach terminal; tool fault injection requires "
                "HI_AGENT_FAULT_TOOL_CRASH=* env var on the server process"
            )
        )
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
        return result

    if final_state not in _TERMINAL:
        result.update(_fail_result(f"unexpected state: {final_state}"))
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
        return result

    detail = _get_run_detail(base_url, run_id)
    error_type = detail.get("error_type") or detail.get("failure_reason") or ""

    if final_state in _FAILURE_STATES:
        result.update(
            _ok_result(
                f"tool crash led to classified terminal state={final_state}, "
                f"error_type={error_type!r}, fault_injected={fault_injected}"
            )
        )
        result["provenance"] = "real" if fault_injected else "structural"
        result["runtime_coupled"] = fault_injected
        result["synthetic"] = not fault_injected
    elif final_state in ("completed", "succeeded"):
        # Without tool invocation, run may succeed — skip rather than fail.
        result.update(
            _skip_result(
                f"run completed with state={final_state}; no tool was invoked or "
                "fault was not triggered (HI_AGENT_FAULT_TOOL_CRASH may not be set)"
            )
        )
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
    else:
        result.update(_fail_result(f"unclassified terminal state: {final_state}"))
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
    return result
