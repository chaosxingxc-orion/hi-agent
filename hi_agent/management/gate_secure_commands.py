"""Secure gate command helpers with JWT and RBAC checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from hi_agent.auth import RBACEnforcer, validate_jwt_claims
from hi_agent.management.gate_api import InMemoryGateAPI
from hi_agent.management.gate_commands import cmd_gate_resolve


class MissingRoleClaimError(ValueError):
    """Raised when role claim is missing or invalid in JWT claims."""


def secure_cmd_gate_resolve(
    *,
    api: InMemoryGateAPI,
    rbac: RBACEnforcer,
    claims: Mapping[str, object],
    required_audience: str,
    gate_ref: str,
    action: str,
    approver: str,
    role_claim_key: str = "role",
    now_fn: Callable[[], float] | None = None,
    comment: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Resolve a gate after validating JWT claims and RBAC permissions."""
    normalized_claims = validate_jwt_claims(
        claims,
        audience=required_audience,
        now_fn=now_fn,
    )
    role_value = normalized_claims.get(role_claim_key)
    if not isinstance(role_value, str) or not role_value.strip():
        raise MissingRoleClaimError(f"missing required role claim: {role_claim_key}")
    return cmd_gate_resolve(
        api,
        gate_ref=gate_ref,
        action=action,
        approver=approver,
        comment=comment,
        reason=reason,
        rbac=rbac,
        approver_role=role_value.strip(),
    )
