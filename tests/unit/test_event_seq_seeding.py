"""Unit tests for per-run _event_seqs dict and storage seeding in RunManager.

Layer 1 -- Unit: per-function tests; event_store mocked only for seed-from-storage
test (to isolate the seeding logic from SQLite I/O).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.server.event_store import SQLiteEventStore, StoredEvent
from hi_agent.server.run_manager import ManagedRun, RunManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(run_id: str = "run-001", tenant_id: str = "t1") -> ManagedRun:
    return ManagedRun(
        run_id=run_id,
        tenant_id=tenant_id,
        user_id="u1",
        session_id="s1",
        task_contract={"goal": "test"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_event_seqs_starts_empty() -> None:
    """_event_seqs dict must be empty on a fresh RunManager instance."""
    rm = RunManager()
    try:
        assert rm._event_seqs == {}
    finally:
        rm.shutdown(timeout=1.0)


def test_first_event_gets_seq_zero() -> None:
    """The first _publish_run_event call for a run allocates sequence=0."""
    store = SQLiteEventStore(db_path=":memory:")
    rm = RunManager()
    rm.set_event_store(store)
    run = _make_run()
    rm._runs[run.run_id] = run
    try:
        rm._publish_run_event(run.run_id, "run_started", {"state": "running"}, run)
        # After first publish, counter must be 1 (next seq will be 1)
        assert rm._event_seqs.get(run.run_id) == 1
        events = store.list_since(run.run_id, since_sequence=-1)
        assert len(events) == 1
        assert events[0].sequence == 0
    finally:
        rm.shutdown(timeout=1.0)
        store.close()


def test_second_event_gets_seq_one_no_collision() -> None:
    """A second event for the same run must get sequence=1 (no collision)."""
    store = SQLiteEventStore(db_path=":memory:")
    rm = RunManager()
    rm.set_event_store(store)
    run = _make_run()
    rm._runs[run.run_id] = run
    try:
        rm._publish_run_event(run.run_id, "run_started", {"state": "running"}, run)
        rm._publish_run_event(run.run_id, "run_completed", {"state": "completed"}, run)
        events = store.list_since(run.run_id, since_sequence=-1)
        assert len(events) == 2
        seqs = [e.sequence for e in events]
        assert seqs == [0, 1], f"Expected [0, 1]; got {seqs}"
    finally:
        rm.shutdown(timeout=1.0)
        store.close()


def test_new_manager_seeds_seq_from_storage() -> None:
    """A new RunManager with an existing event store seeds _event_seqs from max_sequence.

    Mock the event_store.max_sequence method to return a known value so the
    seeding logic is exercised without real SQLite data.
    """
    # Use MagicMock without spec so max_sequence (newly added method) is accessible.
    mock_store = MagicMock()
    # Pretend there are already 5 events stored (sequences 0-4, max=4).
    # max_sequence returns 4; seed = 4 + 1 = 5.
    mock_store.max_sequence.return_value = 4
    # append must not raise
    mock_store.append.return_value = None

    rm = RunManager()
    rm.set_event_store(mock_store)
    run = _make_run(run_id="run-seeded")
    rm._runs[run.run_id] = run
    try:
        # First publish on this fresh RunManager should seed from max_sequence+1 = 5
        rm._publish_run_event(run.run_id, "run_started", {"state": "running"}, run)

        # max_sequence should have been called once for seeding
        mock_store.max_sequence.assert_called_once_with("run-seeded")

        # The event sent to store must carry sequence=5
        call_args = mock_store.append.call_args
        event_arg: StoredEvent = call_args[0][0]
        assert event_arg.sequence == 5, (
            f"Expected seq=5 (seeded from max+1); got {event_arg.sequence}"
        )

        # _event_seqs must now be 6 (next seq)
        assert rm._event_seqs.get("run-seeded") == 6
    finally:
        rm.shutdown(timeout=1.0)


def test_independent_runs_have_independent_seqs() -> None:
    """Two runs must not share sequence counters."""
    store = SQLiteEventStore(db_path=":memory:")
    rm = RunManager()
    rm.set_event_store(store)
    run_a = _make_run(run_id="run-a")
    run_b = _make_run(run_id="run-b")
    rm._runs[run_a.run_id] = run_a
    rm._runs[run_b.run_id] = run_b
    try:
        rm._publish_run_event(run_a.run_id, "run_started", {}, run_a)
        rm._publish_run_event(run_a.run_id, "run_completed", {}, run_a)
        rm._publish_run_event(run_b.run_id, "run_started", {}, run_b)

        events_a = store.list_since(run_a.run_id, since_sequence=-1)
        events_b = store.list_since(run_b.run_id, since_sequence=-1)

        assert [e.sequence for e in events_a] == [0, 1]
        assert [e.sequence for e in events_b] == [0]
    finally:
        rm.shutdown(timeout=1.0)
        store.close()
