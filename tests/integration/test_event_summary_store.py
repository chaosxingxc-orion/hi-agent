"""Unit tests for in-memory runtime event summary store."""

from __future__ import annotations

import pytest
from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore


def test_event_summary_store_put_get_and_list_runs() -> None:
    """Store should return summaries by run ID and list known runs."""
    store = EventSummaryStore()
    store.put_summary("run-b", {"total_events": 2})
    store.put_summary("run-a", {"total_events": 1})

    assert store.get_summary("run-a") == {"total_events": 1}
    assert store.get_summary("run-missing") is None
    assert store.list_runs() == ["run-a", "run-b"]


def test_event_summary_store_overwrite_replaces_previous_payload() -> None:
    """Second put for same run should overwrite previous summary."""
    store = EventSummaryStore()
    store.put_summary("run-1", {"total_events": 1})
    store.put_summary("run-1", {"total_events": 5, "counts_by_type": {"x": 5}})

    assert store.get_summary("run-1") == {
        "total_events": 5,
        "counts_by_type": {"x": 5},
    }


def test_event_summary_store_copy_on_write_and_read_prevents_mutation_leaks() -> None:
    """Store should not expose internal state through caller-owned objects."""
    store = EventSummaryStore()
    payload = {"nested": {"value": 1}}

    store.put_summary("run-1", payload)
    payload["nested"]["value"] = 99
    assert store.get_summary("run-1") == {"nested": {"value": 1}}

    read_back = store.get_summary("run-1")
    assert read_back is not None
    read_back["nested"]["value"] = 7
    assert store.get_summary("run-1") == {"nested": {"value": 1}}


@pytest.mark.parametrize(
    ("run_id", "summary"),
    [
        ("", {"ok": True}),
        ("   ", {"ok": True}),
        ("run-1", "not-a-dict"),
    ],
)
def test_event_summary_store_validation_errors(run_id: str, summary: object) -> None:
    """Invalid run IDs and summary payloads should raise ValueError."""
    store = EventSummaryStore()
    with pytest.raises(ValueError):
        store.put_summary(run_id, summary)  # type: ignore[arg-type]  expiry_wave: permanent
