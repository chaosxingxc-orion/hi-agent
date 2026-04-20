"""Unit tests for decision audit command wrappers."""

from __future__ import annotations

import pytest
from hi_agent.route_engine.decision_audit_commands import (
    cmd_decision_audit_append,
    cmd_decision_audit_latest,
    cmd_decision_audit_list_run,
)
from hi_agent.route_engine.decision_audit_store import InMemoryDecisionAuditStore


def test_cmd_decision_audit_append_and_list_run() -> None:
    """Append command should persist audit and list command should return it."""
    store = InMemoryDecisionAuditStore()
    payload = cmd_decision_audit_append(
        store,
        {"run_id": "run-1", "stage_id": "S1_understand", "selected_branch": "b-1"},
    )
    assert payload["command"] == "decision_audit_append"
    assert payload["audit"]["run_id"] == "run-1"

    listed = cmd_decision_audit_list_run(store, "run-1")
    assert listed["command"] == "decision_audit_list_run"
    assert listed["count"] == 1
    assert listed["audits"][0]["stage_id"] == "S1_understand"


def test_cmd_decision_audit_latest_returns_latest_entry() -> None:
    """Latest command should return most recent stage audit."""
    store = InMemoryDecisionAuditStore()
    cmd_decision_audit_append(store, {"run_id": "run-2", "stage_id": "S2_gather", "ts": 1.0})
    cmd_decision_audit_append(store, {"run_id": "run-2", "stage_id": "S2_gather", "ts": 2.0})

    latest = cmd_decision_audit_latest(store, "run-2", "S2_gather")
    assert latest["command"] == "decision_audit_latest"
    assert latest["audit"]["ts"] == 2.0


@pytest.mark.parametrize("run_id", ["", "   "])
def test_cmd_decision_audit_list_run_validates_run_id(run_id: str) -> None:
    """List command should validate non-empty run_id."""
    store = InMemoryDecisionAuditStore()
    with pytest.raises(ValueError):
        cmd_decision_audit_list_run(store, run_id)


def test_cmd_decision_audit_append_validates_mapping() -> None:
    """Append command should require mapping payload."""
    store = InMemoryDecisionAuditStore()
    with pytest.raises(TypeError):
        cmd_decision_audit_append(store, ["bad"])  # type: ignore[arg-type]
