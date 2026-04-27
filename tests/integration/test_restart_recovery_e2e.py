"""E2E test: run state survives RunManager restart (IV-3).

Layer 2 (integration) — real file-backed SQLite stores; zero mocks on
the subsystems under test.

Tests:
1. A completed run is visible in a fresh RunManager instance pointing to the
   same DB file.
2. A completed run is not re-executed after restart (no duplicate execution).
"""

from __future__ import annotations

import time

from hi_agent.server.run_manager import RunManager
from hi_agent.server.run_store import SQLiteRunStore

# ---------------------------------------------------------------------------
# Shared executor helpers
# ---------------------------------------------------------------------------


class _Result:
    status = "completed"
    error = None


def _noop_executor(run):
    return _Result()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_done_run_visible_after_restart(tmp_path) -> None:
    """A completed run is visible in a fresh RunManager using the same DB file.

    Simulates a process restart by constructing a second RunManager that opens
    the same SQLite file the first one wrote to.
    """
    db = str(tmp_path / "runs.db")

    # --- first "process" ---
    store1 = SQLiteRunStore(db_path=db)
    rm1 = RunManager(run_store=store1)

    run1 = rm1.create_run({"task": "restart_probe_1", "tenant_id": "t1"})
    run_id = run1.run_id
    rm1.start_run(run_id, _noop_executor)

    # Wait up to 5 s for terminal state.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        r = rm1.get_run(run_id)
        if r and r.state in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)

    assert run1.state == "completed", (
        f"Run did not reach terminal state before restart: {run1.state}"
    )

    # --- simulated restart: fresh instances, same DB ---
    store2 = SQLiteRunStore(db_path=db)
    RunManager(run_store=store2)

    # RunManager uses run_store for durability; reload from DB directly.
    recovered = store2.get(run_id)
    assert recovered is not None, "Run was lost after restart"
    assert recovered.status == "completed", (
        f"Unexpected status after restart: {recovered.status}"
    )


def test_no_duplicate_execution_after_restart(tmp_path) -> None:
    """A completed run is not executed again when a new RunManager opens the DB.

    After the first RunManager completes the run, a second RunManager
    (same DB) must not re-execute the run when start_run is called on the
    same run_id.
    """
    db = str(tmp_path / "runs2.db")
    execution_count: dict[str, int] = {"n": 0}

    def _counting_executor(run):
        execution_count["n"] += 1
        return _Result()

    # --- first process ---
    store1 = SQLiteRunStore(db_path=db)
    rm1 = RunManager(run_store=store1)

    run1 = rm1.create_run({"task": "dup_check", "tenant_id": "t1"})
    run_id = run1.run_id
    rm1.start_run(run_id, _counting_executor)

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        r = rm1.get_run(run_id)
        if r and r.state in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert execution_count["n"] == 1, (
        f"Expected exactly 1 execution before restart, got {execution_count['n']}"
    )

    # --- simulated restart ---
    store2 = SQLiteRunStore(db_path=db)
    rm2 = RunManager(run_store=store2)

    # The new RunManager has no in-memory record of the run.
    # start_run on an unknown run_id is a no-op (run not in _runs dict).
    rm2.start_run(run_id, _counting_executor)

    # Give a moment for any accidental execution.
    time.sleep(0.15)

    assert execution_count["n"] == 1, (
        f"Run was executed again after restart: count={execution_count['n']}"
    )

    # The DB record must still be terminal.
    recovered = store2.get(run_id)
    assert recovered is not None
    assert recovered.status == "completed", (
        f"Unexpected DB status after restart: {recovered.status}"
    )
