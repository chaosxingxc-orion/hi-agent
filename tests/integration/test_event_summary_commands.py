"""Tests for runtime event summary command wrappers."""

from __future__ import annotations

import pytest
from hi_agent.runtime_adapter.event_summary_commands import (
    cmd_event_summary_get,
    cmd_event_summary_ingest,
    cmd_event_summary_list_runs,
)
from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore


def test_cmd_event_summary_ingest_get_and_list_runs_happy_path() -> None:
    """Ingest should persist summary and make it retrievable/listable."""
    store = EventSummaryStore()
    events = [
        {"type": "StageStarted", "timestamp": 10.0, "run_id": "run-1"},
        {"type": "StageCompleted", "timestamp": 12.5, "run_id": "run-1"},
    ]

    ingest_payload = cmd_event_summary_ingest(store, "run-1", events)
    assert ingest_payload["command"] == "event_summary_ingest"
    assert ingest_payload["summary"]["total_events"] == 2

    get_payload = cmd_event_summary_get(store, "run-1")
    assert get_payload["command"] == "event_summary_get"
    assert get_payload["found"] is True
    assert get_payload["summary"]["duration_ms"] == 2500.0

    list_payload = cmd_event_summary_list_runs(store)
    assert list_payload == {
        "command": "event_summary_list_runs",
        "count": 1,
        "runs": ["run-1"],
    }


def test_cmd_event_summary_get_returns_not_found_for_unknown_run() -> None:
    """Get command should return found=False when summary does not exist."""
    store = EventSummaryStore()
    payload = cmd_event_summary_get(store, "missing")
    assert payload["found"] is False
    assert payload["summary"] is None


@pytest.mark.parametrize("bad_run_id", ["", "   "])
def test_cmd_event_summary_rejects_empty_run_id(bad_run_id: str) -> None:
    """Commands should reject empty run IDs."""
    store = EventSummaryStore()
    with pytest.raises(ValueError):
        cmd_event_summary_ingest(store, bad_run_id, [])
    with pytest.raises(ValueError):
        cmd_event_summary_get(store, bad_run_id)


def test_cmd_event_summary_rejects_invalid_store_and_events() -> None:
    """Commands should validate store type and event iterable input."""
    store = EventSummaryStore()
    with pytest.raises(TypeError):
        cmd_event_summary_ingest(object(), "run-1", [])
    with pytest.raises(TypeError):
        cmd_event_summary_get(object(), "run-1")
    with pytest.raises(TypeError):
        cmd_event_summary_list_runs(object())
    with pytest.raises(TypeError):
        cmd_event_summary_ingest(store, "run-1", 123)  # type: ignore[arg-type]  expiry_wave: Wave 27
