"""Utilities for summarizing runtime event streams."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def summarize_runtime_events(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize runtime events into dashboard-friendly aggregate fields.

    Args:
      events: Iterable of event dictionaries. Each event may include:
        - `type`: event type string.
        - `timestamp`: UNIX timestamp in seconds.
        - `run_id`: ignored by this summarizer but allowed in input.

    Returns:
      A summary payload containing:
        - `counts_by_type`: type -> count
        - `first_event_ts`: minimum valid timestamp or None
        - `last_event_ts`: maximum valid timestamp or None
        - `duration_ms`: millisecond delta between first/last or None
        - `total_events`: total number of received items
    """
    counts_by_type: dict[str, int] = {}
    first_event_ts: float | None = None
    last_event_ts: float | None = None
    total_events = 0

    for event in events:
        total_events += 1
        event_type = _normalize_event_type(event)
        counts_by_type[event_type] = counts_by_type.get(event_type, 0) + 1

        timestamp = _extract_timestamp(event)
        if timestamp is None:
            continue
        if first_event_ts is None or timestamp < first_event_ts:
            first_event_ts = timestamp
        if last_event_ts is None or timestamp > last_event_ts:
            last_event_ts = timestamp

    duration_ms: float | None = None
    if first_event_ts is not None and last_event_ts is not None:
        duration_ms = max(0.0, (last_event_ts - first_event_ts) * 1000.0)

    return {
        "counts_by_type": counts_by_type,
        "first_event_ts": first_event_ts,
        "last_event_ts": last_event_ts,
        "duration_ms": duration_ms,
        "total_events": total_events,
    }


def _normalize_event_type(event: dict[str, Any]) -> str:
    """Return stable event type value for aggregation."""
    event_type = event.get("type")
    if isinstance(event_type, str) and event_type.strip():
        return event_type.strip()
    return "unknown"


def _extract_timestamp(event: dict[str, Any]) -> float | None:
    """Extract numeric timestamp from one event dictionary."""
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, int | float):
        return None
    return float(timestamp)
