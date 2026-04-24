"""Smoke test: hi_agent.runtime_adapter.event_signals_bridge importable and callable."""
import pytest


@pytest.mark.smoke
def test_build_signals_from_event_summary_importable():
    """build_signals_from_event_summary can be imported without error."""
    from hi_agent.runtime_adapter.event_signals_bridge import build_signals_from_event_summary

    assert build_signals_from_event_summary is not None


@pytest.mark.smoke
def test_build_signals_from_event_summary_basic():
    """build_signals_from_event_summary returns a dict for a minimal valid summary."""
    from hi_agent.runtime_adapter.event_signals_bridge import build_signals_from_event_summary

    summary = {
        "counts_by_type": {"ActionPlanned": 2, "ActionExecuted": 1},
        "total_events": 3,
        "duration_ms": 500,
        "first_event_ts": 1000.0,
        "last_event_ts": 1001.0,
    }
    result = build_signals_from_event_summary(summary)
    assert isinstance(result, dict)


@pytest.mark.smoke
def test_build_signals_rejects_negative_backlog_threshold():
    """build_signals_from_event_summary raises ValueError for negative threshold."""
    from hi_agent.runtime_adapter.event_signals_bridge import build_signals_from_event_summary

    summary = {
        "counts_by_type": {},
        "total_events": 0,
        "duration_ms": 0,
    }
    with pytest.raises(ValueError):
        build_signals_from_event_summary(summary, backlog_threshold=-1)
