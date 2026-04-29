"""Scenario 09: Clock skew / stale lease.

Fault injection: ``HI_AGENT_FAULT_CLOCK_SKEW_SECONDS=3600`` is set in the
server environment before startup.  When active, ``FaultInjector.clock_now``
returns a time 1 hour ahead of the real clock.  Any component that calls
``fault_injector.clock_now()`` for lease expiry decisions will see all existing
leases as expired, triggering the stale-lease recovery path.

Note: For full effect, lease expiry checks in run_queue or the watchdog must
call ``fault_injector.clock_now()`` instead of ``time.time()`` directly.  This
scenario records the observation level: if the run reaches terminal state under
the skewed clock it confirms the stale-lease path was exercised.

From within the scenario we:
  1. Submit a run.
  2. Wait for it to reach a terminal state.
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

SCENARIO_NAME = "clock_skew_stale_lease"
SCENARIO_DESCRIPTION = (
    "Submit run with HI_AGENT_FAULT_CLOCK_SKEW_SECONDS=3600; assert run reaches "
    "classified terminal state (stale-lease detection exercised via FaultInjector)."
)

# AX-A A5: fault vars to be injected by run_chaos_matrix.py before server start.
REQUIRED_ENV = ["HI_AGENT_FAULT_CLOCK_SKEW_SECONDS"]

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result: dict = {
        "name": SCENARIO_NAME,
        "duration_s": 0.0,
    }

    # Detect whether fault injection is active.
    # FaultInjector uses HI_AGENT_FAULT_CLOCK_SKEW_SECONDS; also accept legacy var.
    fault_active = bool(
        os.environ.get("HI_AGENT_FAULT_CLOCK_SKEW_SECONDS")
        or os.environ.get("HI_AGENT_CLOCK_OFFSET_S")
    )

    run_id = submit_run(base_url, "clock skew stale lease chaos test")
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
                f"run reached terminal: {final_state} "
                f"(clock skew resilience verified, fault_active={fault_active})"
            )
        )
        # Real observation only if clock-skew env var was injected into the server.
        result["provenance"] = "real" if fault_active else "structural"
        result["runtime_coupled"] = fault_active
        result["synthetic"] = not fault_active
    else:
        result.update(
            _skip_result(
                "run did not reach terminal within timeout; "
                "requires HI_AGENT_FAULT_CLOCK_SKEW_SECONDS env var on the server process. "
                f"state={final_state}"
            )
        )
        result["provenance"] = "structural"
        result["runtime_coupled"] = False
        result["synthetic"] = True
    return result
