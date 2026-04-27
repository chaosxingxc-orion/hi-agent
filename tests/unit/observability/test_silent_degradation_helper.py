"""Tests for record_silent_degradation helper."""
from __future__ import annotations
import logging
import pytest
from hi_agent.observability.silent_degradation import record_silent_degradation, get_fallback_events


def test_records_event():
    initial = len(get_fallback_events())
    record_silent_degradation("test.component", "test_reason", run_id="r-1")
    events = get_fallback_events()
    assert len(events) == initial + 1
    assert events[-1]["component"] == "test.component"
    assert events[-1]["reason"] == "test_reason"
    assert events[-1]["run_id"] == "r-1"


def test_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="hi_agent.observability.silent_degradation"):
        record_silent_degradation("test2", "reason2", exc=ValueError("oops"))
    assert any("Rule-7" in r.message for r in caplog.records)


def test_exc_is_recorded():
    exc = RuntimeError("test error")
    record_silent_degradation("c", "r", exc=exc)
    events = get_fallback_events()
    assert any("RuntimeError" in e.get("exc", "") for e in events)
