"""Scenario 03: Database lock/busy condition.

Verifies the server degrades gracefully under SQLite contention.
"""
from __future__ import annotations

import threading

from _helpers import _fail_result, _ok_result, submit_run, wait_terminal

SCENARIO_NAME = "db_lock_busy"
SCENARIO_DESCRIPTION = "Submit run under simulated database contention (threading lock)."

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
    # Submit multiple runs concurrently to stress SQLite WAL
    run_ids: list[str] = []

    def _submit() -> None:
        rid = submit_run(base_url, "db contention test")
        if rid:
            run_ids.append(rid)

    threads = [threading.Thread(target=_submit) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    if not run_ids:
        result.update(_fail_result("no runs submitted"))
        return result
    # Wait for all runs to complete
    terminal_count = 0
    for rid in run_ids:
        state = wait_terminal(base_url, rid, timeout=max(timeout - 10, 20))
        if state != "timeout":
            terminal_count += 1
    if terminal_count == len(run_ids):
        result.update(
            _ok_result(f"all {len(run_ids)} concurrent runs reached terminal")
        )
    elif terminal_count > 0:
        result.update(
            _ok_result(
                f"{terminal_count}/{len(run_ids)} runs reached terminal under contention"
            )
        )
    else:
        result.update(_fail_result("no runs reached terminal under contention"))
    return result
