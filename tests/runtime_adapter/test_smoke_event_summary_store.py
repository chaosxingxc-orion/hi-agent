"""Smoke test: hi_agent.runtime_adapter.event_summary_store importable and instantiable."""
import pytest


@pytest.mark.smoke
def test_event_summary_store_importable():
    """EventSummaryStore can be imported without error."""
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    assert EventSummaryStore is not None


@pytest.mark.smoke
def test_event_summary_store_instantiable():
    """EventSummaryStore can be instantiated with no args."""
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    store = EventSummaryStore()
    assert store is not None


@pytest.mark.smoke
def test_event_summary_store_list_runs_empty():
    """EventSummaryStore.list_runs returns empty list initially."""
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    store = EventSummaryStore()
    assert store.list_runs() == []


@pytest.mark.smoke
def test_event_summary_store_put_and_get():
    """EventSummaryStore stores and retrieves a summary by run_id."""
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    store = EventSummaryStore()
    summary = {"total_events": 5, "counts_by_type": {"ActionPlanned": 5}}
    store.put_summary("run-abc", summary)
    result = store.get_summary("run-abc")
    assert result is not None
    assert result["total_events"] == 5


@pytest.mark.smoke
def test_event_summary_store_get_unknown_returns_none():
    """EventSummaryStore.get_summary returns None for unknown run_id."""
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    store = EventSummaryStore()
    assert store.get_summary("no-such-run") is None


@pytest.mark.smoke
def test_event_summary_store_rejects_empty_run_id():
    """EventSummaryStore.put_summary raises ValueError for empty run_id."""
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    store = EventSummaryStore()
    with pytest.raises(ValueError):
        store.put_summary("", {"total_events": 0})
