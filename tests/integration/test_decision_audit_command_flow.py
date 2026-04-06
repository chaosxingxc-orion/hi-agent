"""Integration flow tests for decision audit command wrappers."""

from __future__ import annotations

from hi_agent.route_engine.decision_audit_commands import (
    cmd_decision_audit_append,
    cmd_decision_audit_latest,
    cmd_decision_audit_list_run,
)
from hi_agent.route_engine.decision_audit_store import InMemoryDecisionAuditStore


def test_decision_audit_command_flow_append_list_latest() -> None:
    """Append/list/latest commands should stay consistent in one flow."""
    store = InMemoryDecisionAuditStore()

    first = cmd_decision_audit_append(
        store,
        {
            "run_id": "run-flow-1",
            "stage_id": "S2_gather",
            "selected_branch": "b-1",
            "confidence": 0.63,
            "ts": 100.0,
        },
    )
    second = cmd_decision_audit_append(
        store,
        {
            "run_id": "run-flow-1",
            "stage_id": "S2_gather",
            "selected_branch": "b-2",
            "confidence": 0.81,
            "ts": 101.0,
        },
    )
    _third_other_stage = cmd_decision_audit_append(
        store,
        {
            "run_id": "run-flow-1",
            "stage_id": "S3_build",
            "selected_branch": "b-7",
            "confidence": 0.77,
            "ts": 102.0,
        },
    )

    assert first["command"] == "decision_audit_append"
    assert second["command"] == "decision_audit_append"

    listed = cmd_decision_audit_list_run(store, "run-flow-1")
    assert listed["command"] == "decision_audit_list_run"
    assert listed["count"] == 3
    assert [item["selected_branch"] for item in listed["audits"]] == ["b-1", "b-2", "b-7"]

    latest = cmd_decision_audit_latest(store, "run-flow-1", "S2_gather")
    assert latest["command"] == "decision_audit_latest"
    assert latest["audit"] is not None
    assert latest["audit"]["selected_branch"] == "b-2"
    assert latest["audit"]["confidence"] == 0.81
    assert latest["audit"]["ts"] == 101.0
