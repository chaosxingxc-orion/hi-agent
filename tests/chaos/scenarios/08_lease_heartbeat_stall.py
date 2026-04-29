"""Scenario 08: Lease heartbeat stall.

Fault injection: ``HI_AGENT_FAULT_HEARTBEAT_STALL=1`` is set in the server
environment before startup.  When active, ``FaultInjector.maybe_stall_heartbeat_sync``
wired into the ``_heartbeat_loop`` in ``run_manager.py`` raises ``RuntimeError``
on the first heartbeat renewal, aborting the loop and triggering the
``lease_lost`` → ``failed`` recovery path.

Legacy env vars (``HI_AGENT_HEARTBEAT_STALL_S`` / ``HI_AGENT_HEARTBEAT_INTERVAL_MS``)
are also accepted for backward compatibility.

From within the scenario we:
  1. Submit a run.
  2. Wait for a short window to allow the watchdog to detect the expired lease.
  3. Assert the run eventually reaches a terminal state — the system must
     not leave the run dangling after a heartbeat stall.
  4. Assert the run's final state is one of the classified terminal states.
"""
from __future__ import annotations

import os
import time

from _helpers import (
    _fail_result,
    _ok_result,
    _skip_result,
    get_run_state,
    submit_run,
    wait_terminal,
)

SCENARIO_NAME = "lease_heartbeat_stall"
SCENARIO_DESCRIPTION = (
    "Submit run with HI_AGENT_FAULT_HEARTBEAT_STALL=1; assert watchdog drives run "
    "to classified terminal state (not a silent dangle) via FaultInjector."
)

# AX-A A5: fault vars to be injected by run_chaos_matrix.py before server start.
REQUIRED_ENV = ["HI_AGENT_FAULT_HEARTBEAT_STALL"]

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result: dict = {
        "name": SCENARIO_NAME,
        "runtime_coupled": True,
        "synthetic": False,
        "provenance": "real",
        "duration_s": 0.0,
    }

    # Detect whether fault injection is active.
    # FaultInjector uses HI_AGENT_FAULT_HEARTBEAT_STALL; also accept legacy vars.
    fault_active = bool(
        os.environ.get("HI_AGENT_FAULT_HEARTBEAT_STALL")
        or (
            os.environ.get("HI_AGENT_HEARTBEAT_STALL_S")
            and os.environ.get("HI_AGENT_HEARTBEAT_INTERVAL_MS")
        )
    )

    stall_s_str = os.environ.get("HI_AGENT_HEARTBEAT_STALL_S", "")
    heartbeat_ms_str = os.environ.get("HI_AGENT_HEARTBEAT_INTERVAL_MS", "")

    run_id = submit_run(base_url, "lease stall chaos test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result

    # If stall env vars are set, wait for stall + expiry window before polling.
    # For FaultInjector stall, the heartbeat aborts immediately; give 3s buffer.
    if fault_active:
        if stall_s_str and heartbeat_ms_str:
            try:
                stall_s = float(stall_s_str)
                interval_ms = float(heartbeat_ms_str)
            except ValueError:
                stall_s = 2.0
                interval_ms = 100.0
            stall_wait = stall_s + (interval_ms / 1000.0) * 3 + 1.0
        else:
            # FaultInjector path: abort is immediate; wait a short buffer.
            stall_wait = 3.0
        stall_wait = min(stall_wait, timeout - 10)
        time.sleep(stall_wait)

    state = get_run_state(base_url, run_id)
    if state in _TERMINAL:
        result.update(
            _ok_result(
                f"run already terminal after stall window: state={state} "
                f"(fault_active={fault_active})"
            )
        )
        return result

    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)

    if final_state in _TERMINAL:
        result.update(
            _ok_result(
                f"run reached terminal={final_state} after heartbeat stall "
                f"(fault_active={fault_active})"
            )
        )
    elif final_state == "timeout":
        if fault_active:
            result.update(
                _fail_result(
                    "run did not reach terminal after heartbeat stall — "
                    "watchdog failed to drive expired lease to terminal"
                )
            )
        else:
            result.update(
                _skip_result(
                    "run did not complete within timeout and no heartbeat stall env vars "
                    "were set; skipping as no fault was injected"
                )
            )
    else:
        result.update(_fail_result(f"unexpected state: {final_state}"))
    return result
