"""Tests for TraceContextManager and EventEnvelope."""

from __future__ import annotations

import pytest
from hi_agent.events.envelope import EventEnvelope, make_envelope
from hi_agent.observability.trace_context import TraceContextManager


class TestTraceContextManager:
    """TraceContextManager tests."""

    def test_new_trace(self):
        mgr = TraceContextManager()
        ctx = mgr.new_trace()
        assert ctx.trace_id
        assert ctx.span_id
        assert ctx.parent_span_id == ""
        current = mgr.current()
        assert current is not None
        assert current.trace_id == ctx.trace_id
        mgr.clear()

    def test_child_span(self):
        mgr = TraceContextManager()
        root = mgr.new_trace()
        child = mgr.child_span()
        assert child.trace_id == root.trace_id
        assert child.span_id != root.span_id
        assert child.parent_span_id == root.span_id
        mgr.clear()

    def test_child_span_without_trace_raises(self):
        mgr = TraceContextManager()
        mgr.clear()
        with pytest.raises(RuntimeError, match="No active trace context"):
            mgr.child_span()

    def test_nested_parent_chain(self):
        mgr = TraceContextManager()
        with mgr.span("root") as root:
            with mgr.span("child") as child:
                with mgr.span("grandchild") as gc:
                    assert gc.trace_id == root.trace_id
                    assert gc.parent_span_id == child.span_id
                # After grandchild exits, should be back to child
                current = mgr.current()
                assert current is not None
                assert current.span_id == child.span_id
            # After child exits, should be back to root
            current = mgr.current()
            assert current is not None
            assert current.span_id == root.span_id
        mgr.clear()

    def test_span_restores_context(self):
        mgr = TraceContextManager()
        mgr.clear()
        assert mgr.current() is None
        with mgr.span("root") as root:
            assert mgr.current() is not None
        # After span exits, previous (None) is restored
        assert mgr.current() is None


class TestEventEnvelope:
    """EventEnvelope fields tests."""

    def test_fields(self):
        env = EventEnvelope(
            event_type="StageStateChanged",
            run_id="run-1",
            payload={"stage_id": "S1", "to_state": "completed"},
            timestamp="2026-01-01T00:00:00Z",
            trace_id="t1",
            span_id="s1",
            parent_span_id="p1",
        )
        assert env.event_type == "StageStateChanged"
        assert env.run_id == "run-1"
        assert env.payload["stage_id"] == "S1"
        assert env.trace_id == "t1"
        assert env.span_id == "s1"
        assert env.parent_span_id == "p1"

    def test_make_envelope(self):
        env = make_envelope(
            event_type="TaskViewRecorded",
            run_id="run-2",
            payload={"tokens": 100},
            trace_id="t2",
        )
        assert env.event_type == "TaskViewRecorded"
        assert env.run_id == "run-2"
        assert env.timestamp  # should be non-empty
        assert env.trace_id == "t2"

    def test_default_trace_fields(self):
        env = EventEnvelope(
            event_type="test",
            run_id="r1",
            payload={},
            timestamp="now",
        )
        assert env.trace_id == ""
        assert env.span_id == ""
        assert env.parent_span_id == ""
