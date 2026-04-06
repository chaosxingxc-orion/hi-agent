"""Unit tests for command auth context builder."""

from __future__ import annotations

import pytest
from hi_agent.auth.command_context import (
    CommandAuthContext,
    InvalidClaimError,
    MissingClaimError,
    build_command_context_from_claims,
)


def test_build_command_context_from_claims_success_defaults() -> None:
    """Builder should read `sub` and `role` by default."""
    claims = {"sub": "user-1", "role": "admin", "aud": "hi-agent"}
    ctx = build_command_context_from_claims(claims)
    assert isinstance(ctx, CommandAuthContext)
    assert ctx.user_id == "user-1"
    assert ctx.role == "admin"
    assert ctx.claims["aud"] == "hi-agent"


def test_build_command_context_from_claims_success_custom_keys() -> None:
    """Builder should support custom claim-key mapping."""
    claims = {"uid": "user-2", "permissions_role": "reviewer"}
    ctx = build_command_context_from_claims(
        claims,
        role_claim_key="permissions_role",
        user_claim_key="uid",
    )
    assert ctx.user_id == "user-2"
    assert ctx.role == "reviewer"


@pytest.mark.parametrize("claims", [{}, {"sub": "u"}, {"role": "ops"}])
def test_build_command_context_missing_required_claims(claims: dict[str, object]) -> None:
    """Missing user/role claims should raise typed missing-claim error."""
    with pytest.raises(MissingClaimError):
        build_command_context_from_claims(claims)


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "u", "role": ""},
        {"sub": "u", "role": "   "},
        {"sub": "", "role": "ops"},
        {"sub": "u", "role": 1},
        {"sub": 2, "role": "ops"},
    ],
)
def test_build_command_context_invalid_required_claims(claims: dict[str, object]) -> None:
    """Invalid claim value types/content should raise typed invalid-claim error."""
    with pytest.raises(InvalidClaimError):
        build_command_context_from_claims(claims)


def test_build_command_context_validates_claim_key_args() -> None:
    """Claim-key arguments should be validated up front."""
    with pytest.raises(ValueError):
        build_command_context_from_claims({"sub": "u", "role": "ops"}, role_claim_key="")
    with pytest.raises(ValueError):
        build_command_context_from_claims({"sub": "u", "role": "ops"}, user_claim_key=" ")
