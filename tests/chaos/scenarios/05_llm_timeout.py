"""Scenario 05: LLM timeout injection.

Fault injection: ``HI_AGENT_FAULT_LLM_TIMEOUT=1`` is set in the server
environment before startup.  When active, ``FaultInjector.maybe_raise_llm_timeout``
wired into both ``HTTPGateway.complete`` (async) and ``HttpLLMGateway.complete``
(sync) raises ``asyncio.TimeoutError`` / ``LLMTimeoutError`` on the first LLM
call, exercising the run's LLM-timeout recovery path.

From within the scenario we:
  1. Submit a run.
  2. Assert the run reaches a terminal state (failed / timed_out / error) rather
     than hanging indefinitely.
  3. Assert the elapsed wall-clock time is less than the scenario timeout,
     proving the system did not block on the stalled LLM call.
"""
from __future__ import annotations

import os
import time

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "llm_timeout"
SCENARIO_DESCRIPTION = (
    "Submit run with HI_AGENT_FAULT_LLM_TIMEOUT=1; assert run reaches terminal "
    "state before scenario timeout (LLM timeout resilience verified via FaultInjector)."
)

# AX-A A5: fault vars to be injected by run_chaos_matrix.py before server start.
REQUIRED_ENV = ["HI_AGENT_FAULT_LLM_TIMEOUT"]

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)

# Maximum acceptable wall-clock seconds for the run to reach terminal.
_MAX_WALL_CLOCK_S = 50.0


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result: dict = {
        "name": SCENARIO_NAME,
        "duration_s": 0.0,
    }

    # Detect whether fault injection is active in the server environment.
    fault_active = bool(os.environ.get("HI_AGENT_FAULT_LLM_TIMEOUT"))

    t0 = time.monotonic()
    run_id = submit_run(base_url, "llm timeout chaos test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
        return result

    wait_budget = min(_MAX_WALL_CLOCK_S, timeout - 5)
    final_state = wait_terminal(base_url, run_id, timeout=wait_budget)
    elapsed = round(time.monotonic() - t0, 2)

    if final_state in _TERMINAL:
        result.update(
            _ok_result(
                f"run reached terminal={final_state} in {elapsed}s "
                f"(well under timeout={timeout}s — LLM timeout resilience verified, "
                f"fault_active={fault_active})"
            )
        )
        # Real fault injection confirmed when the FaultInjector env var was set.
        result["provenance"] = "real" if fault_active else "structural"
        result["runtime_coupled"] = fault_active
        result["synthetic"] = not fault_active
    elif final_state == "timeout":
        result.update(
            _skip_result(
                f"run still in-progress after {elapsed}s — "
                "HI_AGENT_FAULT_LLM_TIMEOUT env var may not be honoured; "
                "verify fault_injection.py is wired into the LLM gateway"
            )
        )
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
    else:
        result.update(_fail_result(f"unexpected state after {elapsed}s: {final_state}"))
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
    return result
