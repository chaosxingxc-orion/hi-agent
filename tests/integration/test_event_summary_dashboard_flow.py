"""Integration flow combining event summary and dashboard payload."""

from __future__ import annotations

from hi_agent.management.operational_dashboard import build_operational_dashboard_payload
from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events
from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore


def test_event_summary_store_to_dashboard_flow() -> None:
    """Summarized events should be storable and visible in dashboard metadata."""
    summary = summarize_runtime_events(
        [
            {"type": "StageStarted", "timestamp": 1.0, "run_id": "run-1"},
            {"type": "StageCompleted", "timestamp": 2.0, "run_id": "run-1"},
        ]
    )
    store = EventSummaryStore()
    store.put_summary("run-1", summary)

    payload = build_operational_dashboard_payload(
        readiness_report={"ready": True},
        operational_signals={"overall_pressure": False},
        metadata={"event_summary": store.get_summary("run-1")},
    )

    assert payload["status_badge"] == "green"
    assert payload["metadata"]["event_summary"]["total_events"] == 2
