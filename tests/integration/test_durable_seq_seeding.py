"""Durable sequence seeding: SQLiteEventStore restart-survival tests (IV-4).

Layer 2 (integration) — real file-backed SQLite; zero mocks on the subsystem
under test.

Tests:
1. Events written in one store instance are readable in a second instance
   pointing to the same DB file.
2. max_sequence(run_id) returns the correct MAX after restart.
"""

from __future__ import annotations

import uuid

from hi_agent.server.event_store import SQLiteEventStore, StoredEvent


class TestEventStoreRestart:
    """SQLiteEventStore restart-survival proofs."""

    def test_events_survive_store_restart(self, tmp_path) -> None:
        """Events written by instance s1 are readable by fresh instance s2."""
        db = str(tmp_path / "events.db")
        run_id = str(uuid.uuid4())

        s1 = SQLiteEventStore(db_path=db)
        for i in range(3):
            s1.append(StoredEvent(
                event_id=str(uuid.uuid4()),
                run_id=run_id,
                sequence=i,
                event_type="test_event",
                payload_json=f'{{"i":{i}}}',
            ))

        # Restart: open same file with a new instance.
        s2 = SQLiteEventStore(db_path=db)
        events = s2.list_since(run_id, -1)
        assert len(events) == 3, f"Expected 3 events after restart, got {len(events)}"
        assert s2.max_sequence(run_id) == 2

    def test_max_sequence_seeds_correctly(self, tmp_path) -> None:
        """max_sequence returns the stored MAX (not -1) after restart."""
        db = str(tmp_path / "events2.db")
        run_id = "r-seed-test-" + str(uuid.uuid4())

        s1 = SQLiteEventStore(db_path=db)
        s1.append(StoredEvent(
            event_id=str(uuid.uuid4()),
            run_id=run_id,
            sequence=42,
            event_type="probe",
            payload_json="{}",
        ))

        s2 = SQLiteEventStore(db_path=db)
        assert s2.max_sequence(run_id) == 42

    def test_list_since_returns_correct_slice_after_restart(self, tmp_path) -> None:
        """list_since(run_id, threshold) works correctly after restart."""
        db = str(tmp_path / "events3.db")
        run_id = str(uuid.uuid4())

        s1 = SQLiteEventStore(db_path=db)
        for i in range(5):
            s1.append(StoredEvent(
                event_id=str(uuid.uuid4()),
                run_id=run_id,
                sequence=i,
                event_type="evt",
                payload_json=f'{{"seq":{i}}}',
            ))

        s2 = SQLiteEventStore(db_path=db)
        # list_since returns events with sequence > threshold.
        events_after_2 = s2.list_since(run_id, 2)
        seqs = [e.sequence for e in events_after_2]
        assert seqs == [3, 4], f"Unexpected sequences: {seqs}"
