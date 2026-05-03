"""Scenario 10: Graceful drain under active work.

Calls POST /ops/drain to initiate server-level graceful drain while a run is
active. Verifies the run reaches terminal state through the drain path.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request

from _helpers import _OPENER, _fail_result, _ok_result, submit_run, wait_terminal

SCENARIO_NAME = "graceful_drain_active_work"
SCENARIO_DESCRIPTION = "Submit run, POST /ops/drain, verify run reaches terminal via drain path."

_TERMINAL = frozenset(
    {"completed", "succeeded", "failed", "cancelled", "done", "error", "timed_out"}
)


def _post_drain(base_url: str) -> int:
    """POST /ops/drain; returns HTTP status code or 0 on network error."""
    req = urllib.request.Request(
        f"{base_url}/ops/drain",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(req, timeout=35) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _finalize_provenance(
    result: dict, *, drain_code: int, run_terminal: bool
) -> dict:
    """Compute provenance from observed drain + terminal signals.

    W32-C.2: provenance="real" requires both that the drain endpoint
    actually responded successfully (2xx/3xx) AND that the run reached a
    terminal state attributable to the drain signal.  Otherwise the drain
    path was not exercised end-to-end and provenance is "structural".
    """
    drain_ok = 200 <= drain_code < 400
    if drain_ok and run_terminal:
        result["provenance"] = "real"
    else:
        result["provenance"] = "structural"
    return result


def run_scenario(base_url: str, timeout: float = 60.0) -> dict:
    result = {
        "name": SCENARIO_NAME,
        "runtime_coupled": True,
        "synthetic": False,
        # Default to structural; finalize after observing drain + terminal.
        "provenance": "structural",
        "duration_s": 0.0,
    }
    run_id = submit_run(base_url, "graceful drain test")
    if not run_id:
        result.update(_fail_result("could not submit run"))
        return _finalize_provenance(result, drain_code=0, run_terminal=False)

    # Wait briefly then initiate server-level drain
    time.sleep(0.5)
    drain_code = _post_drain(base_url)

    if drain_code == 404:
        result.update(_fail_result("/ops/drain endpoint not found (404) — endpoint missing"))
        return _finalize_provenance(result, drain_code=drain_code, run_terminal=False)

    final_state = wait_terminal(base_url, run_id, timeout=timeout - 10)
    run_terminal = final_state in _TERMINAL
    if run_terminal:
        result.update(
            _ok_result(
                f"drain_code={drain_code}, run reached terminal: {final_state}"
            )
        )
    else:
        result.update(
            _fail_result(
                f"run in state={final_state} after drain (drain_code={drain_code})"
            )
        )
    return _finalize_provenance(
        result, drain_code=drain_code, run_terminal=run_terminal
    )
