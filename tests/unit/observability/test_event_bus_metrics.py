"""Tests that event_bus observer drops increment the Rule 7 counter.

Layer 1 -- Unit (no external network; uses in-process EventBus only).
"""
from __future__ import annotations

import logging
import uuid

from agent_kernel.kernel.contracts import RuntimeEvent
from hi_agent.server.event_bus import EventBus


def _make_event(run_id: str) -> RuntimeEvent:
    """Build a minimal valid RuntimeEvent for testing."""
    eid = str(uuid.uuid4())
    return RuntimeEvent(
        run_id=run_id,
        event_id=eid,
        commit_offset=0,
        event_type="test.event",
        event_class="fact",
        event_authority="authoritative_fact",
        ordering_key="0",
        wake_policy="wake_actor",
        created_at="2026-01-01T00:00:00Z",
    )


def test_observer_exception_increments_drop_counter():
    """When a sync observer raises, _total_dropped increments by 1."""
    bus = EventBus()

    def bad_observer(event):
        raise ValueError("observer failure")

    bus.add_sync_observer(bad_observer)
    event = _make_event(str(uuid.uuid4()))
    initial_dropped = bus._total_dropped
    bus.publish(event)
    assert bus._total_dropped == initial_dropped + 1


def test_observer_exception_logs_warning(caplog):
    """When a sync observer raises, a WARNING is logged mentioning Rule 7."""
    bus = EventBus()

    def bad_observer(event):
        raise RuntimeError("bad observer")

    bus.add_sync_observer(bad_observer)
    event = _make_event(str(uuid.uuid4()))
    with caplog.at_level(logging.WARNING, logger="hi_agent.server.event_bus"):
        bus.publish(event)
    assert any(
        "Rule 7" in r.message or "observer" in r.message.lower()
        for r in caplog.records
    ), f"Expected Rule 7 warning; got records: {[r.message for r in caplog.records]}"


def test_observer_exception_increments_prometheus_counter():
    """When a sync observer raises and a collector is registered, counter increments."""
    from hi_agent.observability.collector import (
        MetricsCollector,
        set_metrics_collector,
    )

    collector = MetricsCollector()
    set_metrics_collector(collector)
    try:
        bus = EventBus()

        def bad_observer(event):
            raise ValueError("test error")

        bus.add_sync_observer(bad_observer)
        event = _make_event(str(uuid.uuid4()))
        bus.publish(event)

        snap = collector.snapshot()
        drop_count = snap.get("hi_agent_event_bus_observer_drop_total", {}).get("_total", 0)
        assert drop_count == 1, f"Expected counter=1, got {drop_count}"
    finally:
        set_metrics_collector(None)


def test_good_observer_does_not_increment_drop_counter():
    """When a sync observer succeeds, _total_dropped stays at 0."""
    bus = EventBus()
    received = []

    def good_observer(event):
        received.append(event)

    bus.add_sync_observer(good_observer)
    event = _make_event(str(uuid.uuid4()))
    bus.publish(event)
    assert bus._total_dropped == 0
    assert len(received) == 1
