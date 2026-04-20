"""Integration tests for SQLiteEventStore persistence and replay semantics."""
from __future__ import annotations

from hi_agent.server.event_store import SQLiteEventStore, StoredEvent


def _evt(event_id: str, run_id: str, sequence: int, event_type: str = "test") -> StoredEvent:
    return StoredEvent(
        event_id=event_id,
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        payload_json=f'{{"seq": {sequence}}}',
        created_at=0.0,
    )


class TestSQLiteEventStore:
    """SQLiteEventStore stores events durably and replays them correctly."""

    def test_list_since_returns_events_after_sequence(self):
        """list_since(run_id, 3) returns only events with sequence > 3."""
        store = SQLiteEventStore(":memory:")
        for i in range(1, 6):
            store.append(_evt(f"e{i}", "run-A", i))

        result = store.list_since("run-A", 3)

        sequences = [e.sequence for e in result]
        assert sequences == [4, 5]
        store.close()

    def test_list_since_ordered_by_sequence(self):
        """Events are returned in ascending sequence order."""
        store = SQLiteEventStore(":memory:")
        # Insert out of order
        for seq in [3, 1, 2]:
            store.append(_evt(f"e{seq}", "run-B", seq))

        result = store.list_since("run-B", 0)
        assert [e.sequence for e in result] == [1, 2, 3]
        store.close()

    def test_duplicate_event_id_is_idempotent(self):
        """Appending the same event_id twice results in exactly one row."""
        store = SQLiteEventStore(":memory:")
        ev = _evt("dup-1", "run-C", 1)
        store.append(ev)
        store.append(ev)  # second append must be silently ignored

        result = store.list_since("run-C", 0)
        assert len(result) == 1
        store.close()

    def test_run_isolation(self):
        """Events for run-A do not appear in queries for run-B."""
        store = SQLiteEventStore(":memory:")
        store.append(_evt("a1", "run-A", 1))
        store.append(_evt("b1", "run-B", 1))

        a_events = store.list_since("run-A", 0)
        b_events = store.list_since("run-B", 0)

        assert all(e.run_id == "run-A" for e in a_events)
        assert all(e.run_id == "run-B" for e in b_events)
        assert len(a_events) == 1
        assert len(b_events) == 1
        store.close()

    def test_list_since_zero_returns_all(self):
        """list_since with since_sequence=0 returns all events."""
        store = SQLiteEventStore(":memory:")
        for i in range(1, 4):
            store.append(_evt(f"z{i}", "run-Z", i))

        result = store.list_since("run-Z", 0)
        assert len(result) == 3
        store.close()

    def test_empty_run_returns_empty_list(self):
        """Querying an unknown run_id returns an empty list."""
        store = SQLiteEventStore(":memory:")
        result = store.list_since("no-such-run", 0)
        assert result == []
        store.close()
