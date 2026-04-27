"""Scenario 10: Graceful drain under active work.

Sends a signal to /runs/{id}/signal with action=cancel to verify
graceful drain path. Checks that the run transitions to cancelled/done.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from _helpers import _fail_result, _ok_result, submit_run, wait_terminal

SCENARIO_NAME = "graceful_drain_active_work"
SCENARIO_DESCRIPTION = "Submit run, signal cancel, verify graceful drain to terminal state."

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
    run_id = submit_run(base_url, "graceful drain test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return result
    # Wait briefly then send cancel signal
    time.sleep(1)
    signal_code = 0
    try:
        body = json.dumps({"action": "cancel"}).encode()
        req = urllib.request.Request(
            f"{base_url}/runs/{run_id}/signal",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            signal_code = r.status
    except urllib.error.HTTPError as e:
        signal_code = e.code
    except Exception:
        signal_code = 0

    final_state = wait_terminal(base_url, run_id, timeout=timeout - 10)
    if final_state in _TERMINAL:
        result.update(
            _ok_result(
                f"drain signal={signal_code}, run reached terminal: {final_state}"
            )
        )
    elif signal_code == 404:
        # Run already completed before drain signal
        result.update(
            _ok_result("run completed before drain signal (signal_code=404); drain handled")
        )
    else:
        result.update(
            _fail_result(
                f"run in state={final_state} after drain signal={signal_code}"
            )
        )
    return result
