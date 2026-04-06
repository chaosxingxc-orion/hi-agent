"""Command-style wrappers for operational timeline helpers."""

from __future__ import annotations

from typing import Any

from hi_agent.management.ops_timeline import build_ops_timeline


def cmd_ops_timeline_build(
    events: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build timeline payload from source rows."""
    timeline = build_ops_timeline(events=events, audits=audits, incidents=incidents)
    return {"command": "ops_timeline_build", "count": len(timeline), "timeline": timeline}


def cmd_ops_timeline_slice(
    timeline: list[dict[str, Any]],
    *,
    start_ts: float | None = None,
    end_ts: float | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Slice timeline by optional timestamp range and limit."""
    if not isinstance(timeline, list):
        raise TypeError("timeline must be a list")
    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        raise ValueError("start_ts must be <= end_ts")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be > 0 when provided")

    rows: list[dict[str, Any]] = []
    for item in timeline:
        if not isinstance(item, dict):
            continue
        ts = item.get("ts")
        if isinstance(ts, int | float):
            ts_value = float(ts)
            if start_ts is not None and ts_value < start_ts:
                continue
            if end_ts is not None and ts_value > end_ts:
                continue
        rows.append(dict(item))

    if limit is not None:
        rows = rows[:limit]
    return {"command": "ops_timeline_slice", "count": len(rows), "timeline": rows}
