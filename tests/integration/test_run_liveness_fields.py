"""Integration tests for W12-C: /runs/{id} liveness fields.

Profile validated: default-offline
"""

from __future__ import annotations

import time

from hi_agent.server.event_store import SQLiteEventStore, StoredEvent
from hi_agent.server.run_manager import ManagedRun, RunManager


def _make_manager(event_store=None) -> RunManager:
    return RunManager(max_concurrent=2, queue_size=4, event_store=event_store)


def test_liveness_fields_present_on_completed_run() -> None:
    """started_at is populated after a sync executor completes the run."""
    mgr = _make_manager()
    run = mgr.create_run({"task": "hello"})

    def _executor(r: ManagedRun):
        return type(
            "R", (), {"status": "completed", "llm_fallback_count": 0, "finished_at": None}
        )()

    mgr.start_run(run.run_id, _executor)
    # Wait for the worker to finish
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if run.state in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)

    assert run.state == "completed", f"unexpected state: {run.state}"
    d = mgr.to_dict(run)
    assert d["started_at"] is not None, "started_at must be set after run executes"
    assert d["state"] == "completed"
    # Fields present (even if None)
    assert "last_heartbeat_at" in d
    assert "last_event_offset" in d
    assert "last_event_at" in d
    assert "current_action_id" in d
    assert "no_progress_seconds" in d
    mgr.shutdown()


def test_last_event_offset_populated() -> None:
    """last_event_offset is non-negative after events are written to the event store."""
    import uuid

    event_store = SQLiteEventStore(":memory:")
    mgr = _make_manager(event_store=event_store)
    run = mgr.create_run({"task": "with-events"})

    # Write a synthetic event so list_since returns something
    event_store.append(
        StoredEvent(
            event_id=str(uuid.uuid4()),
            run_id=run.run_id,
            sequence=1,
            event_type="test_event",
            payload_json="{}",
        )
    )

    def _executor(r: ManagedRun):
        return type(
            "R", (), {"status": "completed", "llm_fallback_count": 0, "finished_at": None}
        )()

    mgr.start_run(run.run_id, _executor)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if run.state in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)

    d = mgr.to_dict(run)
    assert d["last_event_offset"] is not None, "last_event_offset must be set when events exist"
    assert d["last_event_offset"] >= 1
    assert d["last_event_at"] is not None
    mgr.shutdown()
    event_store.close()


def test_no_progress_seconds_is_none_for_new_run() -> None:
    """A just-created run with no heartbeat/events has no_progress_seconds=None."""
    mgr = _make_manager()
    run = mgr.create_run({"task": "idle"})

    d = mgr.to_dict(run)
    assert d["no_progress_seconds"] is None, (
        "no_progress_seconds must be None when neither heartbeat nor events recorded"
    )
    mgr.shutdown()
