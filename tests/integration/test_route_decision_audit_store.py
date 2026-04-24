"""Tests for in-memory route decision audit store."""

from __future__ import annotations

import pytest
from hi_agent.route_engine.decision_audit_store import InMemoryDecisionAuditStore


def test_list_by_run_preserves_insertion_order() -> None:
    """Audits for one run should keep append order."""
    store = InMemoryDecisionAuditStore()
    store.append({"run_id": "run-1", "stage_id": "S1", "selected_branch": "b1"})
    store.append({"run_id": "run-2", "stage_id": "S1", "selected_branch": "x1"})
    store.append({"run_id": "run-1", "stage_id": "S2", "selected_branch": "b2"})

    rows = store.list_by_run("run-1")
    assert [row["stage_id"] for row in rows] == ["S1", "S2"]
    assert [row["selected_branch"] for row in rows] == ["b1", "b2"]


def test_latest_by_stage_returns_most_recent_match() -> None:
    """Latest audit for run/stage should come from newest append."""
    store = InMemoryDecisionAuditStore()
    store.append({"run_id": "run-1", "stage_id": "S2", "selected_branch": "old"})
    store.append({"run_id": "run-1", "stage_id": "S2", "selected_branch": "new"})
    store.append({"run_id": "run-1", "stage_id": "S3", "selected_branch": "other"})

    latest = store.latest_by_stage("run-1", "S2")
    assert latest is not None
    assert latest["selected_branch"] == "new"
    assert store.latest_by_stage("run-1", "S9") is None


def test_store_returns_defensive_copies() -> None:
    """Mutating returned rows should not alter stored state."""
    store = InMemoryDecisionAuditStore()
    appended = store.append({"run_id": "run-1", "stage_id": "S1", "selected_branch": "b1"})
    appended["selected_branch"] = "changed"

    listed = store.list_by_run("run-1")
    listed[0]["selected_branch"] = "listed-changed"

    latest = store.latest_by_stage("run-1", "S1")
    assert latest is not None
    assert latest["selected_branch"] == "b1"


@pytest.mark.parametrize(
    "audit",
    [
        {"run_id": "", "stage_id": "S1"},
        {"run_id": "run-1", "stage_id": ""},
        {"run_id": "run-1"},
        {"stage_id": "S1"},
    ],
)
def test_append_validates_required_fields(audit: dict[str, object]) -> None:
    """Append should reject missing or blank run_id/stage_id."""
    store = InMemoryDecisionAuditStore()
    with pytest.raises(ValueError):
        store.append(audit)
