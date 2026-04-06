"""Integration flow for runtime event summarization and storage."""

from __future__ import annotations

from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events
from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore


def test_runtime_event_summary_can_be_summarized_and_stored() -> None:
    """Summarized events should round-trip through EventSummaryStore."""
    events = [
        {"run_id": "run-1", "type": "StageStateChanged", "timestamp": 10.0},
        {"run_id": "run-1", "type": "ActionExecuted", "timestamp": 11.5},
        {"run_id": "run-1", "type": "ActionExecuted", "timestamp": 12.0},
        {"run_id": "run-1", "type": "", "timestamp": "bad-ts"},
    ]

    summary = summarize_runtime_events(events)
    store = EventSummaryStore()
    store.put_summary("run-1", summary)

    stored = store.get_summary("run-1")
    assert stored is not None
    assert stored["total_events"] == 4
    assert stored["counts_by_type"]["ActionExecuted"] == 2
    assert stored["counts_by_type"]["unknown"] == 1
    assert stored["duration_ms"] == 2000.0

    # copy-on-read safety
    stored["total_events"] = 999
    stored_again = store.get_summary("run-1")
    assert stored_again is not None
    assert stored_again["total_events"] == 4
