"""Tests for EventBus asyncio fan-out."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from hi_agent.server.event_bus import EventBus

# Minimal RuntimeEvent stand-in to avoid kernel import issues.
try:
    from agent_kernel.kernel.contracts import RuntimeEvent
except ImportError:
    RuntimeEvent = None


def _make_event(run_id: str = "r1", event_type: str = "test"):
    """Create a minimal RuntimeEvent-compatible object."""
    if RuntimeEvent is not None:
        return RuntimeEvent(
            run_id=run_id,
            event_id="e1",
            commit_offset=0,
            event_type=event_type,
            event_class="fact",
            event_authority="kernel",
            ordering_key="0",
            wake_policy="always",
            created_at="2026-01-01T00:00:00Z",
        )
    # Fallback dataclass if import fails
    @dataclass
    class _FakeEvent:
        run_id: str
        event_type: str = "test"
    return _FakeEvent(run_id=run_id, event_type=event_type)


class TestEventBus:
    """EventBus tests."""

    def test_queue_maxsize(self):
        bus = EventBus(max_queue_size=5)
        q = bus.subscribe("r1")
        assert q.maxsize == 5

    def test_old_events_dropped_when_full(self):
        bus = EventBus(max_queue_size=2)
        q = bus.subscribe("r1")
        bus.publish(_make_event("r1"))
        bus.publish(_make_event("r1"))
        bus.publish(_make_event("r1"))
        # Queue should still have 2 items (oldest dropped)
        assert q.qsize() == 2
        stats = bus.get_stats()
        assert stats["total_dropped"] >= 1

    def test_get_stats(self):
        bus = EventBus()
        bus.subscribe("r1")
        bus.subscribe("r2")
        stats = bus.get_stats()
        assert stats["subscriber_count"] == 2
        assert stats["total_published"] == 0
        assert stats["total_dropped"] == 0

    def test_unsubscribe(self):
        bus = EventBus()
        q = bus.subscribe("r1")
        assert bus.get_stats()["subscriber_count"] == 1
        bus.unsubscribe("r1", q)
        assert bus.get_stats()["subscriber_count"] == 0

    def test_multiple_subscribers_independent(self):
        bus = EventBus()
        q1 = bus.subscribe("r1")
        q2 = bus.subscribe("r1")
        bus.publish(_make_event("r1"))
        assert q1.qsize() == 1
        assert q2.qsize() == 1
        stats = bus.get_stats()
        assert stats["total_published"] == 2  # one per subscriber

    def test_dropped_count(self):
        bus = EventBus(max_queue_size=1)
        q = bus.subscribe("r1")
        bus.publish(_make_event("r1"))
        bus.publish(_make_event("r1"))
        bus.publish(_make_event("r1"))
        assert bus.get_stats()["total_dropped"] == 2
