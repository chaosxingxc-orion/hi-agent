"""Tests for runtime event stream summarization utility."""

from __future__ import annotations

from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events


def test_summarize_runtime_events_empty_input() -> None:
    """Empty input should return zero totals and no timestamps."""
    summary = summarize_runtime_events([])
    assert summary == {
        "counts_by_type": {},
        "first_event_ts": None,
        "last_event_ts": None,
        "duration_ms": None,
        "total_events": 0,
    }


def test_summarize_runtime_events_counts_types_and_duration() -> None:
    """Summary should aggregate counts and use min/max valid timestamps."""
    events = [
        {"type": "StageStarted", "timestamp": 12.0, "run_id": "r-1"},
        {"type": "ActionExecuted", "timestamp": 13.5, "run_id": "r-1"},
        {"type": "StageStarted", "timestamp": 11.0, "run_id": "r-1"},
    ]
    summary = summarize_runtime_events(events)

    assert summary["counts_by_type"] == {
        "StageStarted": 2,
        "ActionExecuted": 1,
    }
    assert summary["first_event_ts"] == 11.0
    assert summary["last_event_ts"] == 13.5
    assert summary["duration_ms"] == 2500.0
    assert summary["total_events"] == 3


def test_summarize_runtime_events_handles_missing_or_invalid_fields() -> None:
    """Missing type/timestamp should not break summary computation."""
    events = [
        {"type": "", "timestamp": "bad"},
        {"timestamp": 100},
        {"type": "ActionExecuted"},
        {"type": "ActionExecuted", "timestamp": 101.25},
    ]
    summary = summarize_runtime_events(events)

    assert summary["counts_by_type"] == {"unknown": 2, "ActionExecuted": 2}
    assert summary["first_event_ts"] == 100.0
    assert summary["last_event_ts"] == 101.25
    assert summary["duration_ms"] == 1250.0
    assert summary["total_events"] == 4


def test_summarize_runtime_events_mixed_partial_events_keep_stable_counts() -> None:
    """Mixed valid/invalid rows should preserve stable count aggregation."""
    events = [
        {},
        {"type": "StageStarted"},
        {"type": "StageStarted", "timestamp": None},
        {"type": " ", "timestamp": 5},
        {"type": "ActionExecuted", "timestamp": "7"},
        {"type": "ActionExecuted", "timestamp": 8.5},
    ]

    summary = summarize_runtime_events(events)

    assert summary["counts_by_type"] == {
        "unknown": 2,
        "StageStarted": 2,
        "ActionExecuted": 2,
    }
    assert summary["first_event_ts"] == 5.0
    assert summary["last_event_ts"] == 8.5
    assert summary["duration_ms"] == 3500.0
    assert summary["total_events"] == 6
