"""Unit tests for auth claim validation, RBAC, and SoC guards."""

from __future__ import annotations

import pytest
from hi_agent.auth import (
    InvalidAudienceError,
    MissingClaimError,
    OperationNotAllowedError,
    RBACEnforcer,
    SeparationOfConcernError,
    TokenExpiredError,
    UnknownOperationError,
    enforce_submitter_approver_separation,
    validate_jwt_claims,
)


def test_validate_jwt_claims_accepts_valid_claims_with_string_audience() -> None:
    """Validator should accept a token with matching string audience."""
    claims = {"sub": "user-1", "aud": "hi-agent", "exp": 100.0}

    normalized = validate_jwt_claims(claims, audience="hi-agent", now_fn=lambda: 10.0)

    assert normalized["sub"] == "user-1"
    assert normalized["aud"] == "hi-agent"
    assert normalized["exp"] == 100.0


def test_validate_jwt_claims_accepts_valid_claims_with_list_audience() -> None:
    """Validator should accept a token when required audience is in list."""
    claims = {"sub": "user-1", "aud": ["foo", "hi-agent"], "exp": 100.0}
    validate_jwt_claims(claims, audience="hi-agent", now_fn=lambda: 10.0)


def test_validate_jwt_claims_rejects_missing_required_claims() -> None:
    """Validator should reject tokens missing sub/aud/exp claims."""
    with pytest.raises(MissingClaimError):
        validate_jwt_claims({"aud": "hi-agent", "exp": 100}, audience="hi-agent")
    with pytest.raises(MissingClaimError):
        validate_jwt_claims({"sub": "u1", "exp": 100}, audience="hi-agent")
    with pytest.raises(MissingClaimError):
        validate_jwt_claims({"sub": "u1", "aud": "hi-agent"}, audience="hi-agent")


def test_validate_jwt_claims_rejects_invalid_audience() -> None:
    """Validator should reject token when required audience is absent."""
    with pytest.raises(InvalidAudienceError):
        validate_jwt_claims(
            {"sub": "u1", "aud": ["foo", "bar"], "exp": 100},
            audience="hi-agent",
            now_fn=lambda: 10.0,
        )


def test_validate_jwt_claims_rejects_expired_token() -> None:
    """Validator should reject token whose exp is not in the future."""
    with pytest.raises(TokenExpiredError):
        validate_jwt_claims(
            {"sub": "u1", "aud": "hi-agent", "exp": 10},
            audience="hi-agent",
            now_fn=lambda: 10.0,
        )


def test_rbac_enforcer_allows_and_denies_by_policy() -> None:
    """RBAC enforcer should allow permitted roles and deny others."""
    enforcer = RBACEnforcer(
        {
            "management.gate.resolve": {"admin", "approver"},
            "management.runtime.update": {"admin"},
        }
    )

    enforcer.enforce(role="admin", operation="management.runtime.update")

    with pytest.raises(OperationNotAllowedError):
        enforcer.enforce(role="approver", operation="management.runtime.update")


def test_rbac_enforcer_rejects_unknown_operation() -> None:
    """RBAC enforcer should reject operations outside policy map."""
    enforcer = RBACEnforcer({"known": {"admin"}})
    with pytest.raises(UnknownOperationError):
        enforcer.enforce(role="admin", operation="unknown")


def test_soc_guard_blocks_same_principal_when_enabled() -> None:
    """SoC guard should block approval by the original submitter."""
    with pytest.raises(SeparationOfConcernError):
        enforce_submitter_approver_separation(submitter="alice", approver="alice", enabled=True)


def test_soc_guard_allows_when_disabled() -> None:
    """SoC guard should be bypassed when policy is disabled."""
    enforce_submitter_approver_separation(submitter="alice", approver="alice", enabled=False)
