"""Integration test for secure gate resolve workflow."""

from __future__ import annotations

import pytest
from hi_agent.auth.rbac_enforcer import RBACEnforcer
from hi_agent.management.gate_api import InMemoryGateAPI
from hi_agent.management.gate_context import build_gate_context
from hi_agent.management.gate_secure_commands import MissingRoleClaimError, secure_cmd_gate_resolve


def test_secure_cmd_gate_resolve_happy_path() -> None:
    """Valid claims + allowed role should resolve a gate."""
    gate_api = InMemoryGateAPI(now_fn=lambda: 200.0)
    gate_api.create_gate(
        context=build_gate_context(
            gate_ref="gate-sec-1",
            run_id="run-1",
            stage_id="S4_synthesize",
            branch_id="b-1",
            submitter="planner",
            now_fn=lambda: 100.0,
        )
    )

    response = secure_cmd_gate_resolve(
        api=gate_api,
        rbac=RBACEnforcer({"management.gate.resolve": {"reviewer"}}),
        claims={"sub": "alice", "role": "reviewer", "aud": "hi-agent", "exp": 9999999999},
        required_audience="hi-agent",
        gate_ref="gate-sec-1",
        action="approve",
        approver="alice",
    )

    assert response["status"] == "approved"


def test_secure_cmd_gate_resolve_reject_path() -> None:
    """Allowed role should be able to reject a pending gate."""
    gate_api = InMemoryGateAPI(now_fn=lambda: 200.0)
    gate_api.create_gate(
        context=build_gate_context(
            gate_ref="gate-sec-2",
            run_id="run-2",
            stage_id="S4_synthesize",
            branch_id="b-1",
            submitter="planner",
            now_fn=lambda: 100.0,
        )
    )

    response = secure_cmd_gate_resolve(
        api=gate_api,
        rbac=RBACEnforcer({"management.gate.resolve": {"reviewer"}}),
        claims={"sub": "alice", "role": "reviewer", "aud": "hi-agent", "exp": 9999999999},
        required_audience="hi-agent",
        gate_ref="gate-sec-2",
        action="reject",
        approver="alice",
        reason="insufficient-evidence",
    )
    assert response["status"] == "rejected"


def test_secure_cmd_gate_resolve_denies_soc_approve() -> None:
    """Submitter cannot approve when SoC is enabled."""
    gate_api = InMemoryGateAPI(now_fn=lambda: 200.0)
    gate_api.create_gate(
        context=build_gate_context(
            gate_ref="gate-sec-3",
            run_id="run-3",
            stage_id="S4_synthesize",
            branch_id="b-1",
            submitter="author",
            now_fn=lambda: 100.0,
        )
    )

    with pytest.raises(PermissionError):
        secure_cmd_gate_resolve(
            api=gate_api,
            rbac=RBACEnforcer({"management.gate.resolve": {"author"}}),
            claims={"sub": "author", "role": "author", "aud": "hi-agent", "exp": 9999999999},
            required_audience="hi-agent",
            gate_ref="gate-sec-3",
            action="approve",
            approver="author",
        )


def test_secure_cmd_gate_resolve_denies_rbac_and_missing_role_claim() -> None:
    """RBAC deny and missing role claim should fail explicitly."""
    gate_api = InMemoryGateAPI(now_fn=lambda: 200.0)
    gate_api.create_gate(
        context=build_gate_context(
            gate_ref="gate-sec-4",
            run_id="run-4",
            stage_id="S4_synthesize",
            branch_id="b-1",
            submitter="planner",
            now_fn=lambda: 100.0,
        )
    )

    with pytest.raises(PermissionError):
        secure_cmd_gate_resolve(
            api=gate_api,
            rbac=RBACEnforcer({"management.gate.resolve": {"reviewer"}}),
            claims={"sub": "alice", "role": "observer", "aud": "hi-agent", "exp": 9999999999},
            required_audience="hi-agent",
            gate_ref="gate-sec-4",
            action="approve",
            approver="alice",
        )

    with pytest.raises(MissingRoleClaimError):
        secure_cmd_gate_resolve(
            api=gate_api,
            rbac=RBACEnforcer({"management.gate.resolve": {"reviewer"}}),
            claims={"sub": "alice", "aud": "hi-agent", "exp": 9999999999},
            required_audience="hi-agent",
            gate_ref="gate-sec-4",
            action="approve",
            approver="alice",
        )
