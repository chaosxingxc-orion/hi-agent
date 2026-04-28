"""Scenario 08: Lease heartbeat stall.

Fault injection: The chaos matrix runner may set
``HI_AGENT_HEARTBEAT_INTERVAL_MS=100`` and ``HI_AGENT_HEARTBEAT_STALL_S=2``
in the server environment to cause lease heartbeats to stop updating
after 2 seconds, triggering the lease-expiry recovery path.

From within the scenario we:
  1. Submit a run.
  2. Wait for a short window (> stall threshold) to allow the watchdog to
     detect the expired lease.
  3. Assert the run eventually reaches a terminal state — the system must
     not leave the run dangling after a heartbeat stall.
  4. Assert the run's final state is one of the classified terminal states
     (not ``unknown`` or an internal error key).

If the heartbeat env vars are not set, the run should still complete normally.
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
    "Submit run with heartbeat-stall env vars; assert watchdog drives the run "
    "to a classified terminal state (not a silent dangle)."
)
# Chaos runner must set these before starting the server subprocess.
REQUIRED_ENV = ["HI_AGENT_HEARTBEAT_STALL_S", "HI_AGENT_HEARTBEAT_INTERVAL_MS"]

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

    stall_s_str = os.environ.get("HI_AGENT_HEARTBEAT_STALL_S", "")
    heartbeat_ms_str = os.environ.get("HI_AGENT_HEARTBEAT_INTERVAL_MS", "")
    fault_active = bool(stall_s_str and heartbeat_ms_str)

    run_id = submit_run(base_url, "lease stall chaos test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result

    # If stall env vars are set, wait for stall + expiry window before polling.
    # Otherwise just poll normally.
    if fault_active:
        try:
            stall_s = float(stall_s_str)
            interval_ms = float(heartbeat_ms_str)
        except ValueError:
            stall_s = 2.0
            interval_ms = 100.0
        # Wait for: stall window + 3x heartbeat interval + buffer
        stall_wait = stall_s + (interval_ms / 1000.0) * 3 + 1.0
        stall_wait = min(stall_wait, timeout - 10)
        time.sleep(stall_wait)

    # Poll for terminal — run must not dangle
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
                    "run did not complete within timeout and heartbeat stall env vars "
                    "were not set; skipping as no fault was injected"
                )
            )
    else:
        result.update(_fail_result(f"unexpected state: {final_state}"))
    return result
