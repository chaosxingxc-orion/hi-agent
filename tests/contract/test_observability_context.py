"""Contract tests: published events carry mandatory observability fields."""
from __future__ import annotations

import pytest

from agent_kernel.kernel.contracts import RuntimeEvent
from hi_agent.server.event_bus import EventBus
from hi_agent.server.event_store import SQLiteEventStore, StoredEvent


def _make_runtime_event(run_id: str, sequence: int) -> RuntimeEvent:
    return RuntimeEvent(
        run_id=run_id,
        event_id=f"evt-{sequence}",
        commit_offset=sequence,
        event_type="test.event",
        event_class="fact",
        event_authority="authoritative_fact",
        ordering_key=str(sequence),
        wake_policy="wake_actor",
        created_at="2026-01-01T00:00:00Z",
    )


class TestEventBusPersistenceContract:
    """Events published to a bus with a store have run_id and sequence populated."""

    def test_published_event_has_run_id(self):
        store = SQLiteEventStore(":memory:")
        bus = EventBus(event_store=store)
        event = _make_runtime_event("run-contract-1", 7)
        bus.publish(event)

        rows = store.list_since("run-contract-1", 0)
        assert len(rows) == 1
        assert rows[0].run_id == "run-contract-1"
        store.close()

    def test_published_event_has_sequence(self):
        store = SQLiteEventStore(":memory:")
        bus = EventBus(event_store=store)
        event = _make_runtime_event("run-contract-2", 42)
        bus.publish(event)

        rows = store.list_since("run-contract-2", 0)
        assert len(rows) == 1
        assert rows[0].sequence == 42
        store.close()

    def test_list_since_returns_in_sequence_order(self):
        store = SQLiteEventStore(":memory:")
        bus = EventBus(event_store=store)
        # Publish 5 events with increasing sequence
        for seq in [1, 2, 3, 4, 5]:
            bus.publish(_make_runtime_event("run-order", seq))

        rows = store.list_since("run-order", 0)
        assert [r.sequence for r in rows] == [1, 2, 3, 4, 5]
        store.close()

    def test_no_store_bus_behavior_unchanged(self):
        """When event_store=None the bus works exactly as before."""
        bus = EventBus()  # no store
        q = bus.subscribe("run-no-store")
        event = _make_runtime_event("run-no-store", 1)
        bus.publish(event)
        assert q.qsize() == 1
        bus.unsubscribe("run-no-store", q)
