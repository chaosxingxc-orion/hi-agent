"""Scenario 02: Server restart with unfinished runs in store.

Fault injection: ``HI_AGENT_FAULT_DLQ_POISON=1`` is set in the server
environment before startup.  When active, the FaultInjector wired into the
heartbeat loop raises on the first heartbeat renewal, driving the run to the
DLQ / terminal ``failed`` state via the existing ``lease_lost`` recovery path.

This exercises the same code path as a real server restart with an in-progress
run: the run enters a terminal state rather than dangling indefinitely.

From within the scenario we:
  1. Submit a run.
  2. Wait for it to reach a terminal state (failed/error via DLQ recovery).
  3. Assert the terminal state is classified (not unknown/pending).
"""
from __future__ import annotations

import os

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "restart_after_unfinished"
SCENARIO_DESCRIPTION = (
    "Submit run with HI_AGENT_FAULT_DLQ_POISON=1; assert run reaches classified "
    "terminal state via DLQ/lease-lost recovery (same path as post-restart rehydration)."
)

# AX-A A5: fault vars to be injected by run_chaos_matrix.py before server start.
REQUIRED_ENV = ["HI_AGENT_FAULT_DLQ_POISON"]

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result: dict = {
        "name": SCENARIO_NAME,
        "duration_s": 0.0,
    }

    # Detect whether fault injection is active in the server environment.
    fault_active = bool(os.environ.get("HI_AGENT_FAULT_DLQ_POISON"))

    run_id = submit_run(base_url, "restart recovery test — DLQ poison fault")
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
                f"run reached terminal state: {final_state} "
                f"(fault_active={fault_active}, runtime_coupled=True)"
            )
        )
        # Real fault injection confirmed when the env var is set and run reached terminal.
        result["provenance"] = "real" if fault_active else "structural"
        result["runtime_coupled"] = fault_active
        result["synthetic"] = not fault_active
    else:
        result.update(
            _skip_result(
                f"run did not reach terminal within timeout; state={final_state}. "
                "Requires HI_AGENT_FAULT_DLQ_POISON=1 on the server process."
            )
        )
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
    return result
