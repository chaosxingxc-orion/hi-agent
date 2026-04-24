"""Tests for record_fallback required-kwarg enforcement."""

import pytest
from hi_agent.observability.fallback import (
    clear_fallback_events,
    get_fallback_events,
    record_fallback,
)


def test_record_fallback_requires_run_id():
    with pytest.raises(TypeError):
        record_fallback("llm", reason="test")  # no run_id


def test_record_fallback_requires_reason():
    with pytest.raises(TypeError):
        record_fallback("llm", run_id="r123")  # no reason


def test_record_fallback_records_event():
    clear_fallback_events("r-test-001")
    record_fallback("llm", reason="retries_exhausted", run_id="r-test-001")
    events = get_fallback_events("r-test-001")
    assert len(events) == 1
    assert events[0]["kind"] == "llm"
    assert events[0]["reason"] == "retries_exhausted"


def test_record_fallback_system_scope():
    # system-scope sentinel must not raise
    record_fallback("heuristic", reason="startup_warmup", run_id="system")
