"""Tests for gate command helpers and readiness linkage."""

from __future__ import annotations

import pytest
from hi_agent.management.gate_api import InMemoryGateAPI
from hi_agent.management.gate_commands import (
    cmd_gate_list,
    cmd_gate_operational_signal,
    cmd_gate_resolve,
    cmd_gate_status,
)
from hi_agent.management.gate_context import build_gate_context
from hi_agent.management.health import build_operational_readiness_report


def test_cmd_gate_list_status_and_resolve_flow() -> None:
    """Command wrappers should expose create/list/status/resolve lifecycle."""
    api = InMemoryGateAPI(now_fn=lambda: 250.0)
    context = build_gate_context(
        gate_ref="gate-cmd-1",
        run_id="run-1",
        stage_id="S2_gather",
        branch_id="b-1",
        submitter="planner",
        now_fn=lambda: 100.0,
    )
    api.create_gate(context=context)

    listed = cmd_gate_list(api)
    assert listed["command"] == "gate_list"
    assert listed["pending_count"] == 1
    assert listed["pending"][0]["gate_ref"] == "gate-cmd-1"

    status = cmd_gate_status(api, gate_ref="gate-cmd-1")
    assert status["command"] == "gate_status"
    assert status["status"] == "pending"

    resolved = cmd_gate_resolve(
        api,
        gate_ref="gate-cmd-1",
        action="approve",
        approver="reviewer",
        comment="ok",
    )
    assert resolved["command"] == "gate_resolve"
    assert resolved["status"] == "approved"


def test_cmd_gate_resolve_validates_inputs() -> None:
    """Command wrapper should validate primitive user input types."""
    api = InMemoryGateAPI(now_fn=lambda: 200.0)
    context = build_gate_context(
        gate_ref="gate-cmd-2",
        run_id="run-2",
        stage_id="S3_build",
        branch_id="b-2",
        submitter="author",
        now_fn=lambda: 100.0,
    )
    api.create_gate(context=context)

    with pytest.raises(TypeError, match="approver must be a string"):
        cmd_gate_resolve(api, gate_ref="gate-cmd-2", action="approve", approver=123)

    with pytest.raises(ValueError, match="gate_ref must be a non-empty string"):
        cmd_gate_status(api, gate_ref="  ")


def test_gate_operational_signal_marks_stale_and_blocks_readiness() -> None:
    """Stale pending gates should be visible and make operational readiness false."""
    api = InMemoryGateAPI(now_fn=lambda: 200.0)
    context = build_gate_context(
        gate_ref="gate-cmd-3",
        run_id="run-3",
        stage_id="S4_synthesize",
        branch_id="b-3",
        submitter="planner",
        now_fn=lambda: 100.0,
    )
    api.create_gate(context=context)

    signal = cmd_gate_operational_signal(
        api,
        now_seconds=250.0,
        stale_gate_threshold_seconds=120.0,
    )
    assert signal["pending_gate_count"] == 1
    assert signal["has_stale_gates"] is True
    assert signal["oldest_pending_gate_age_seconds"] == 150.0

    readiness = build_operational_readiness_report(
        dependencies={"runtime": True},
        recent_error_count=0,
        reconcile_backlog=0,
        recent_reconcile_failures=0,
        reconcile_backlog_threshold=10,
        pending_gate_count=int(signal["pending_gate_count"]),
        stale_gate_threshold_seconds=float(signal["stale_gate_threshold_seconds"]),
        oldest_pending_gate_age_seconds=float(signal["oldest_pending_gate_age_seconds"]),
    )
    assert readiness.has_stale_gates is True
    assert readiness.pending_gate_count == 1
    assert readiness.ready is False
