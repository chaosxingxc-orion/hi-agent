"""Integration: BACKTRACK and REMEDIATE gate actions (P3.1).

Verifies that InMemoryGateAPI accepts the new action values and transitions
the gate to BACKTRACKED / REMEDIATED status correctly.
"""

from __future__ import annotations

import pytest
from hi_agent.management.gate_api import GateAction, GateStatus, InMemoryGateAPI
from hi_agent.management.gate_context import build_gate_context


def _make_context(gate_ref: str):
    return build_gate_context(
        gate_ref=gate_ref,
        run_id="run-test",
        stage_id="stage-1",
        branch_id="branch-1",
        submitter="author",
    )


def test_backtrack_action_succeeds():
    """BACKTRACK action transitions status to BACKTRACKED."""
    api = InMemoryGateAPI(enforce_separation_of_concerns=False)
    ctx = _make_context("gate-bt-001")
    api.create_gate(context=ctx)
    resolved = api.resolve(gate_ref="gate-bt-001", action="backtrack", approver="reviewer")
    assert resolved.status == GateStatus.BACKTRACKED
    assert resolved.resolution_by == "reviewer"


def test_remediate_action_succeeds():
    """REMEDIATE action transitions status to REMEDIATED."""
    api = InMemoryGateAPI(enforce_separation_of_concerns=False)
    ctx = _make_context("gate-rm-001")
    api.create_gate(context=ctx)
    resolved = api.resolve(gate_ref="gate-rm-001", action="remediate", approver="lead")
    assert resolved.status == GateStatus.REMEDIATED
    assert resolved.resolution_by == "lead"


def test_invalid_action_raises():
    """An unrecognised action raises ValueError with a helpful message."""
    api = InMemoryGateAPI(enforce_separation_of_concerns=False)
    ctx = _make_context("gate-inv-001")
    api.create_gate(context=ctx)
    with pytest.raises(ValueError, match="action must be one of"):
        api.resolve(gate_ref="gate-inv-001", action="noop", approver="reviewer")


def test_approve_and_reject_still_work():
    """Existing APPROVE and REJECT actions remain intact after extension."""
    api = InMemoryGateAPI(enforce_separation_of_concerns=False)
    ctx_a = _make_context("gate-ap-001")
    ctx_r = _make_context("gate-rj-001")
    api.create_gate(context=ctx_a)
    api.create_gate(context=ctx_r)
    r_a = api.resolve(gate_ref="gate-ap-001", action="approve", approver="admin")
    assert r_a.status == GateStatus.APPROVED
    r_r = api.resolve(gate_ref="gate-rj-001", action="reject", approver="admin")
    assert r_r.status == GateStatus.REJECTED


def test_all_new_actions_via_enum():
    """GateAction enum exposes BACKTRACK and REMEDIATE values."""
    assert GateAction.BACKTRACK.value == "backtrack"
    assert GateAction.REMEDIATE.value == "remediate"
    assert GateStatus.BACKTRACKED.value == "backtracked"
    assert GateStatus.REMEDIATED.value == "remediated"
