"""Tests for secure gate command wrappers."""

from __future__ import annotations

import pytest
from hi_agent.auth import OperationNotAllowedError, RBACEnforcer, TokenExpiredError
from hi_agent.auth.jwt_middleware import InvalidAudienceError
from hi_agent.management import InMemoryGateAPI, build_gate_context
from hi_agent.management.gate_secure_commands import (
    MissingRoleClaimError,
    secure_cmd_gate_resolve,
)


def _seed_pending_gate() -> InMemoryGateAPI:
    api = InMemoryGateAPI(now_fn=lambda: 200.0)
    context = build_gate_context(
        gate_ref="gate-secure-1",
        run_id="run-1",
        stage_id="S2_gather",
        branch_id="b-1",
        submitter="planner",
        now_fn=lambda: 100.0,
    )
    api.create_gate(context=context)
    return api


def test_secure_cmd_gate_resolve_success() -> None:
    """Valid JWT and RBAC role should resolve gate."""
    api = _seed_pending_gate()
    rbac = RBACEnforcer({"management.gate.resolve": {"approver"}})
    result = secure_cmd_gate_resolve(
        api=api,
        claims={"sub": "u1", "aud": "hi-agent", "exp": 300, "role": "approver"},
        required_audience="hi-agent",
        rbac=rbac,
        gate_ref="gate-secure-1",
        action="approve",
        approver="reviewer",
        now_fn=lambda: 200.0,
    )
    assert result["status"] == "approved"


def test_secure_cmd_gate_resolve_rejects_invalid_audience() -> None:
    """Audience mismatch should fail before gate resolution."""
    api = _seed_pending_gate()
    rbac = RBACEnforcer({"management.gate.resolve": {"approver"}})
    with pytest.raises(InvalidAudienceError):
        secure_cmd_gate_resolve(
            api=api,
            claims={"sub": "u1", "aud": "other", "exp": 300, "role": "approver"},
            required_audience="hi-agent",
            rbac=rbac,
            gate_ref="gate-secure-1",
            action="approve",
            approver="reviewer",
            now_fn=lambda: 200.0,
        )


def test_secure_cmd_gate_resolve_rejects_expired_token() -> None:
    """Expired claims should fail authentication step."""
    api = _seed_pending_gate()
    rbac = RBACEnforcer({"management.gate.resolve": {"approver"}})
    with pytest.raises(TokenExpiredError):
        secure_cmd_gate_resolve(
            api=api,
            claims={"sub": "u1", "aud": "hi-agent", "exp": 100, "role": "approver"},
            required_audience="hi-agent",
            rbac=rbac,
            gate_ref="gate-secure-1",
            action="approve",
            approver="reviewer",
            now_fn=lambda: 200.0,
        )


def test_secure_cmd_gate_resolve_rejects_missing_role_claim() -> None:
    """Missing role claim should fail before RBAC enforcement."""
    api = _seed_pending_gate()
    rbac = RBACEnforcer({"management.gate.resolve": {"approver"}})
    with pytest.raises(MissingRoleClaimError):
        secure_cmd_gate_resolve(
            api=api,
            claims={"sub": "u1", "aud": "hi-agent", "exp": 300},
            required_audience="hi-agent",
            rbac=rbac,
            gate_ref="gate-secure-1",
            action="approve",
            approver="reviewer",
            now_fn=lambda: 200.0,
        )


def test_secure_cmd_gate_resolve_rejects_disallowed_role() -> None:
    """Role that is not allowed for operation should be denied."""
    api = _seed_pending_gate()
    rbac = RBACEnforcer({"management.gate.resolve": {"approver"}})
    with pytest.raises(OperationNotAllowedError):
        secure_cmd_gate_resolve(
            api=api,
            claims={"sub": "u1", "aud": "hi-agent", "exp": 300, "role": "viewer"},
            required_audience="hi-agent",
            rbac=rbac,
            gate_ref="gate-secure-1",
            action="approve",
            approver="reviewer",
            now_fn=lambda: 200.0,
        )
