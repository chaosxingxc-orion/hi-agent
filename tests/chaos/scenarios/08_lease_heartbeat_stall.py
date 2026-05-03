"""Scenario 08: Lease heartbeat stall.

Fault injection: ``HI_AGENT_FAULT_HEARTBEAT_STALL=1`` is set in the server
environment before startup.  When active, ``FaultInjector.maybe_stall_heartbeat_sync``
wired into the ``_heartbeat_loop`` in ``run_manager.py`` raises ``RuntimeError``
on the first heartbeat renewal, aborting the loop and triggering the
``lease_lost`` -> ``failed`` recovery path.

Legacy env vars (``HI_AGENT_HEARTBEAT_STALL_S`` / ``HI_AGENT_HEARTBEAT_INTERVAL_MS``)
are also accepted for backward compatibility — but only when BOTH are set.
A partial legacy pair (only one set) is rejected with provenance="skip" to
avoid silently misclassifying it as a fault-active run.

From within the scenario we:
  1. Submit a run.
  2. Wait for a short window to allow the watchdog to detect the expired lease.
  3. Assert the run eventually reaches a terminal state — the system must
     not leave the run dangling after a heartbeat stall.
  4. Assert the run's final state is one of the classified terminal states.
"""
from __future__ import annotations

import os
import sys
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


def _detect_fault_active() -> tuple[bool, str | None]:
    """Detect whether fault injection is active.

    W32-C.3: legacy env-var pair (HEARTBEAT_STALL_S + HEARTBEAT_INTERVAL_MS)
    must have BOTH variables set or neither — a partial setup is rejected.

    Returns:
        (fault_active, warning_reason): warning_reason is non-None when the
        legacy pair is partial; the caller must short-circuit to skip in
        that case.
    """
    new_var_set = bool(os.environ.get("HI_AGENT_FAULT_HEARTBEAT_STALL"))
    legacy_stall_s = os.environ.get("HI_AGENT_HEARTBEAT_STALL_S")
    legacy_interval_ms = os.environ.get("HI_AGENT_HEARTBEAT_INTERVAL_MS")
    legacy_pair_complete = bool(legacy_stall_s and legacy_interval_ms)
    legacy_pair_partial = bool(legacy_stall_s) ^ bool(legacy_interval_ms)

    if legacy_pair_partial:
        return False, (
            "legacy heartbeat-stall env-var pair is partial: "
            f"HI_AGENT_HEARTBEAT_STALL_S={legacy_stall_s!r} "
            f"HI_AGENT_HEARTBEAT_INTERVAL_MS={legacy_interval_ms!r}; "
            "BOTH must be set or use HI_AGENT_FAULT_HEARTBEAT_STALL"
        )

    return (new_var_set or legacy_pair_complete), None


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result: dict = {
        "name": SCENARIO_NAME,
        "runtime_coupled": True,
        "synthetic": False,
        # provenance is computed below; default to "skip" so a partial
        # run never silently claims real evidence.
        "provenance": "skip",
        "duration_s": 0.0,
    }

    fault_active, partial_warning = _detect_fault_active()

    # W32-C.3: partial legacy pair -> emit warning + skip (provenance=skip).
    if partial_warning:
        print(
            f"[scenario:{SCENARIO_NAME}] WARNING: {partial_warning}",
            file=sys.stderr,
        )
        result.update(_skip_result(partial_warning))
        result["provenance"] = "skip"
        return result

    stall_s_str = os.environ.get("HI_AGENT_HEARTBEAT_STALL_S", "")
    heartbeat_ms_str = os.environ.get("HI_AGENT_HEARTBEAT_INTERVAL_MS", "")

    run_id = submit_run(base_url, "lease stall chaos test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        # Submission failed entirely; provenance="structural" reflects that
        # we exercised the API but did not observe the fault path.
        result["provenance"] = "structural"
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
        # Real evidence only when fault was actually injected.
        result["provenance"] = "real" if fault_active else "structural"
        return result

    final_state = wait_terminal(base_url, run_id, timeout=timeout - 5)

    if final_state in _TERMINAL:
        result.update(
            _ok_result(
                f"run reached terminal={final_state} after heartbeat stall "
                f"(fault_active={fault_active})"
            )
        )
        result["provenance"] = "real" if fault_active else "structural"
    elif final_state == "timeout":
        if fault_active:
            result.update(
                _fail_result(
                    "run did not reach terminal after heartbeat stall — "
                    "watchdog failed to drive expired lease to terminal"
                )
            )
            result["provenance"] = "structural"
        else:
            result.update(
                _skip_result(
                    "run did not complete within timeout and no heartbeat stall env vars "
                    "were set; skipping as no fault was injected"
                )
            )
            result["provenance"] = "skip"
    else:
        result.update(_fail_result(f"unexpected state: {final_state}"))
        result["provenance"] = "structural"
    return result
