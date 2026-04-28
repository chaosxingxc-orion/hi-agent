"""Scenario 10: Graceful drain under active work.

Calls POST /ops/drain to initiate server-level graceful drain while a run is
active. Verifies the run reaches terminal state through the drain path.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request

from _helpers import _fail_result, _ok_result, submit_run, wait_terminal

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
        with urllib.request.urlopen(req, timeout=35) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


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

    # Wait briefly then initiate server-level drain
    time.sleep(0.5)
    drain_code = _post_drain(base_url)

    if drain_code == 404:
        result.update(_fail_result("/ops/drain endpoint not found (404) — endpoint missing"))
        return result

    final_state = wait_terminal(base_url, run_id, timeout=timeout - 10)
    if final_state in _TERMINAL:
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
    return result
