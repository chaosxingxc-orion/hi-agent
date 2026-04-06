"""Command-style wrappers for runtime event summary flows."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events
from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore


def cmd_event_summary_ingest(
    store: EventSummaryStore,
    run_id: str,
    events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize one runtime event stream and persist the summary."""
    _require_store(store)
    normalized_run_id = _normalize_run_id(run_id)
    if not isinstance(events, Iterable):
        raise TypeError("events must be iterable")
    summary = summarize_runtime_events(events)
    store.put_summary(normalized_run_id, summary)
    return {
        "command": "event_summary_ingest",
        "run_id": normalized_run_id,
        "summary": summary,
    }


def cmd_event_summary_get(store: EventSummaryStore, run_id: str) -> dict[str, Any]:
    """Fetch one stored summary in command payload shape."""
    _require_store(store)
    normalized_run_id = _normalize_run_id(run_id)
    summary = store.get_summary(normalized_run_id)
    return {
        "command": "event_summary_get",
        "run_id": normalized_run_id,
        "found": summary is not None,
        "summary": summary,
    }


def cmd_event_summary_list_runs(store: EventSummaryStore) -> dict[str, Any]:
    """List run IDs currently present in summary store."""
    _require_store(store)
    runs = store.list_runs()
    return {
        "command": "event_summary_list_runs",
        "count": len(runs),
        "runs": runs,
    }


def _require_store(store: object) -> None:
    """Validate store instance type."""
    if not isinstance(store, EventSummaryStore):
        raise TypeError("store must be an EventSummaryStore")


def _normalize_run_id(run_id: str) -> str:
    """Normalize and validate run identifier."""
    if not isinstance(run_id, str):
        raise TypeError("run_id must be a string")
    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must be a non-empty string")
    return normalized
