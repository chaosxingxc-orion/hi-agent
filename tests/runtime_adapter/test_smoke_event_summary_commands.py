"""Smoke test: hi_agent.runtime_adapter.event_summary_commands importable and callable."""
import pytest


@pytest.mark.smoke
def test_cmd_event_summary_ingest_importable():
    """cmd_event_summary_ingest can be imported without error."""
    from hi_agent.runtime_adapter.event_summary_commands import cmd_event_summary_ingest

    assert cmd_event_summary_ingest is not None


@pytest.mark.smoke
def test_cmd_event_summary_get_importable():
    """cmd_event_summary_get can be imported without error."""
    from hi_agent.runtime_adapter.event_summary_commands import cmd_event_summary_get

    assert cmd_event_summary_get is not None


@pytest.mark.smoke
def test_cmd_event_summary_list_runs_importable():
    """cmd_event_summary_list_runs can be imported without error."""
    from hi_agent.runtime_adapter.event_summary_commands import cmd_event_summary_list_runs

    assert cmd_event_summary_list_runs is not None


@pytest.mark.smoke
def test_cmd_event_summary_ingest_basic():
    """cmd_event_summary_ingest stores a summary and returns command payload."""
    from hi_agent.runtime_adapter.event_summary_commands import cmd_event_summary_ingest
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    store = EventSummaryStore()
    result = cmd_event_summary_ingest(store, "run-001", [])
    assert result["command"] == "event_summary_ingest"
    assert result["run_id"] == "run-001"
    assert "summary" in result


@pytest.mark.smoke
def test_cmd_event_summary_get_not_found():
    """cmd_event_summary_get returns found=False for unknown run_id."""
    from hi_agent.runtime_adapter.event_summary_commands import cmd_event_summary_get
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    store = EventSummaryStore()
    result = cmd_event_summary_get(store, "nonexistent-run")
    assert result["found"] is False
    assert result["summary"] is None


@pytest.mark.smoke
def test_cmd_event_summary_list_runs_empty():
    """cmd_event_summary_list_runs returns empty run list for empty store."""
    from hi_agent.runtime_adapter.event_summary_commands import cmd_event_summary_list_runs
    from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore

    store = EventSummaryStore()
    result = cmd_event_summary_list_runs(store)
    assert result["runs"] == []
