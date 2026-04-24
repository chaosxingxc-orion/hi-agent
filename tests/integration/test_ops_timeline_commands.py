"""Unit tests for ops timeline command wrappers."""

from __future__ import annotations

import pytest
from hi_agent.management.ops_timeline_commands import (
    cmd_ops_timeline_build,
    cmd_ops_timeline_slice,
)


def test_cmd_ops_timeline_build_normalizes_and_orders_items() -> None:
    """Build command should return timeline sorted by timestamp ascending."""
    payload = cmd_ops_timeline_build(
        events=[{"timestamp": 20.0, "type": "event_b"}, {"timestamp": 10.0, "type": "event_a"}],
        audits=[{"timestamp": 15.0, "type": "audit_a"}],
        incidents=[],
    )
    assert payload["command"] == "ops_timeline_build"
    assert payload["count"] == 3
    assert [row["ts"] for row in payload["timeline"]] == [10.0, 15.0, 20.0]


def test_cmd_ops_timeline_slice_applies_range_and_limit() -> None:
    """Slice command should apply timestamp filtering then limit."""
    timeline = [
        {"ts": 10.0, "type": "event"},
        {"ts": 20.0, "type": "audit"},
        {"ts": 30.0, "type": "incident"},
    ]
    payload = cmd_ops_timeline_slice(timeline, start_ts=15.0, end_ts=30.0, limit=1)
    assert payload["command"] == "ops_timeline_slice"
    assert payload["count"] == 1
    assert payload["timeline"][0]["ts"] == 20.0


@pytest.mark.parametrize(
    ("start_ts", "end_ts", "limit"),
    [
        (30.0, 20.0, None),
        (None, None, 0),
    ],
)
def test_cmd_ops_timeline_slice_validation(
    start_ts: float | None,
    end_ts: float | None,
    limit: int | None,
) -> None:
    """Invalid parameters should raise ValueError."""
    with pytest.raises(ValueError):
        cmd_ops_timeline_slice([], start_ts=start_ts, end_ts=end_ts, limit=limit)
