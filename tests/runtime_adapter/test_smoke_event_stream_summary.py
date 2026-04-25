"""Smoke test: hi_agent.runtime_adapter.event_stream_summary importable and callable."""

import pytest


@pytest.mark.smoke
def test_summarize_runtime_events_importable():
    """summarize_runtime_events can be imported without error."""
    from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events

    assert summarize_runtime_events is not None


@pytest.mark.smoke
def test_summarize_runtime_events_empty():
    """summarize_runtime_events handles an empty event stream."""
    from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events

    result = summarize_runtime_events([])
    assert isinstance(result, dict)
    assert result["total_events"] == 0
    assert result["counts_by_type"] == {}


@pytest.mark.smoke
def test_summarize_runtime_events_basic():
    """summarize_runtime_events counts event types correctly."""
    from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events

    events = [
        {"type": "ActionPlanned", "timestamp": 1000.0},
        {"type": "ActionExecuted", "timestamp": 1001.0},
        {"type": "ActionPlanned", "timestamp": 1002.0},
    ]
    result = summarize_runtime_events(events)
    assert result["total_events"] == 3
    assert result["counts_by_type"].get("ActionPlanned", 0) == 2
    assert result["counts_by_type"].get("ActionExecuted", 0) == 1
