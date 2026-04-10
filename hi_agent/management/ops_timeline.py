"""Operational timeline normalization helpers."""

from __future__ import annotations

from typing import Any


def build_ops_timeline(
    *,
    events: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a normalized timeline from events/audits/incidents."""
    items: list[dict[str, Any]] = []
    items.extend(_normalize_rows(events, kind="event"))
    items.extend(_normalize_rows(audits, kind="audit"))
    items.extend(_normalize_rows(incidents, kind="incident"))
    return sorted(items, key=_timeline_sort_key)


def _normalize_rows(rows: list[dict[str, Any]], *, kind: str) -> list[dict[str, Any]]:
    """Run _normalize_rows."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_value = row.get("timestamp", row.get("ts"))
        has_ts = isinstance(ts_value, int | float)
        normalized.append(
            {
                "ts": float(ts_value) if has_ts else None,
                "type": kind,
                "title": str(row.get("title", row.get("type", kind))).strip() or kind,
                "details": dict(row),
            }
        )
    return normalized


def _timeline_sort_key(item: dict[str, Any]) -> tuple[int, float]:
    """Run _timeline_sort_key."""
    ts = item.get("ts")
    if isinstance(ts, int | float):
        return (0, float(ts))
    return (1, float("inf"))
