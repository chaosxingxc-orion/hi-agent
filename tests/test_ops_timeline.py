"""Unit tests for operations timeline helper."""

from __future__ import annotations

from hi_agent.management.ops_timeline import build_ops_timeline


def test_build_ops_timeline_orders_by_timestamp_and_groups_types() -> None:
    """Timeline should be sorted by timestamp with normalized item types."""
    timeline = build_ops_timeline(
        events=[{"type": "event_a", "timestamp": 3.0}],
        audits=[{"selected_branch": "b1", "ts": 1.0}],
        incidents=[{"incident_id": "inc-1", "ts": 2.0}],
    )
    assert [item["type"] for item in timeline] == ["audit", "incident", "event"]
    assert [item["ts"] for item in timeline] == [1.0, 2.0, 3.0]


def test_build_ops_timeline_places_missing_timestamps_last() -> None:
    """Rows without timestamp should be placed after timestamped rows."""
    timeline = build_ops_timeline(
        events=[{"type": "event_without_ts"}],
        audits=[{"selected_branch": "b1", "ts": 1.0}],
        incidents=[],
    )
    assert timeline[0]["type"] == "audit"
    assert timeline[1]["type"] == "event"
    assert timeline[1]["ts"] is None
