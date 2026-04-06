"""Unit tests for tracer/span helpers."""

from __future__ import annotations

import pytest
from hi_agent.observability.tracing import Tracer


def test_tracer_records_nested_spans() -> None:
    """Tracer should record both parent and child span metadata."""
    ids = iter(["trace-1", "span-1", "span-2"]).__next__
    times = iter([1.0, 1.2, 1.3, 1.8]).__next__
    tracer = Tracer(id_factory=ids, now_fn=times)

    with tracer.span("root") as root_ctx, tracer.span("child", parent=root_ctx):
        pass

    records = tracer.records()
    assert len(records) == 2
    assert records[0].trace_id == "trace-1"
    assert records[1].parent_span_id == records[0].span_id


def test_tracer_records_error_and_re_raises() -> None:
    """Tracer should preserve error information on exceptional exits."""
    ids = iter(["trace-2", "span-1"]).__next__
    times = iter([2.0, 2.5]).__next__
    tracer = Tracer(id_factory=ids, now_fn=times)

    with pytest.raises(RuntimeError), tracer.span("failing"):
        raise RuntimeError("boom")

    records = tracer.records()
    assert len(records) == 1
    assert records[0].error == "RuntimeError: boom"


def test_tracer_rejects_empty_span_name() -> None:
    """Span names should be validated."""
    tracer = Tracer()
    with pytest.raises(ValueError, match="non-empty"), tracer.span("   "):
        pass
