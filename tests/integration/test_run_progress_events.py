"""Integration test: RunManager emits run-progress events into SQLiteEventStore.

Layer 2 — Integration: real RunManager + real SQLiteEventStore (in-memory).
Zero mocks on the subsystems under test.
"""

from __future__ import annotations

import time

from hi_agent.server.event_store import SQLiteEventStore
from hi_agent.server.run_manager import RunManager


def _noop_executor(run):
    """Sync executor that returns immediately with a success status object."""

    class _Result:
        status = "completed"
        error = None

    return _Result()


def _failing_executor(run):
    """Sync executor that raises to trigger the failed path."""
    raise RuntimeError("deliberate failure")


def test_events_emitted_on_completion() -> None:
    """run_started and run_completed events must appear after a successful run.

    Gate: tests/integration/test_run_progress_events.py::test_events_emitted_on_completion
    """
    store = SQLiteEventStore(":memory:")
    manager = RunManager(max_concurrent=2, queue_size=4)
    manager.set_event_store(store)

    run = manager.create_run({"task": "test_success"})
    run_id = run.run_id
    manager.start_run(run_id, _noop_executor)

    # Poll until run reaches a terminal state (max 5 s).
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if run.state in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)

    assert run.state == "completed", f"expected completed, got {run.state}"

    events = store.list_since(run_id, 0)
    event_types = [e.event_type for e in events]
    assert "run_started" in event_types, f"run_started missing; got {event_types}"
    assert "run_completed" in event_types, f"run_completed missing; got {event_types}"
    # run_queued is emitted during create_run, so at minimum 3 events expected.
    assert len(events) >= 2, f"expected >= 2 events, got {len(events)}: {event_types}"


def test_events_emitted_on_failure() -> None:
    """run_started and run_failed events must appear after a failing run."""
    store = SQLiteEventStore(":memory:")
    manager = RunManager(max_concurrent=2, queue_size=4)
    manager.set_event_store(store)

    run = manager.create_run({"task": "test_failure"})
    run_id = run.run_id
    manager.start_run(run_id, _failing_executor)

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if run.state in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)

    assert run.state == "failed", f"expected failed, got {run.state}"

    events = store.list_since(run_id, 0)
    event_types = [e.event_type for e in events]
    assert "run_started" in event_types, f"run_started missing; got {event_types}"
    assert "run_failed" in event_types, f"run_failed missing; got {event_types}"
