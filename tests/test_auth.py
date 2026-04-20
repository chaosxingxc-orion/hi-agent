"""Tests for auth subsystem: JWT validation, RBAC enforcement, SOC guard."""

from __future__ import annotations

from time import time

import pytest
from hi_agent.auth.jwt_middleware import (
    InvalidAudienceError,
    MissingClaimError,
    TokenExpiredError,
    validate_jwt_claims,
)
from hi_agent.auth.rbac_enforcer import (
    OperationNotAllowedError,
    RBACEnforcer,
    UnknownOperationError,
)
from hi_agent.auth.soc_guard import (
    SeparationOfConcernError,
    enforce_submitter_approver_separation,
)

# ---------------------------------------------------------------------------
# JWT validation
# ---------------------------------------------------------------------------

class TestJWTValidation:
    def _valid_claims(self) -> dict:
        return {"sub": "user-1", "aud": "hi-agent", "exp": int(time()) + 3600}

    def test_valid_token(self):
        result = validate_jwt_claims(self._valid_claims(), audience="hi-agent")
        assert result["sub"] == "user-1"

    def test_expired_token(self):
        claims = self._valid_claims()
        claims["exp"] = int(time()) - 100
        with pytest.raises(TokenExpiredError):
            validate_jwt_claims(claims, audience="hi-agent")

    def test_missing_sub(self):
        claims = self._valid_claims()
        del claims["sub"]
        with pytest.raises(MissingClaimError, match="sub"):
            validate_jwt_claims(claims, audience="hi-agent")

    def test_missing_aud(self):
        claims = self._valid_claims()
        del claims["aud"]
        with pytest.raises(MissingClaimError, match="aud"):
            validate_jwt_claims(claims, audience="hi-agent")

    def test_missing_exp(self):
        claims = self._valid_claims()
        del claims["exp"]
        with pytest.raises(MissingClaimError, match="exp"):
            validate_jwt_claims(claims, audience="hi-agent")

    def test_wrong_audience(self):
        claims = self._valid_claims()
        with pytest.raises(InvalidAudienceError):
            validate_jwt_claims(claims, audience="other-service")

    def test_audience_as_list(self):
        claims = self._valid_claims()
        claims["aud"] = ["hi-agent", "other"]
        result = validate_jwt_claims(claims, audience="hi-agent")
        assert result["sub"] == "user-1"

    def test_empty_sub(self):
        claims = self._valid_claims()
        claims["sub"] = "  "
        with pytest.raises(MissingClaimError):
            validate_jwt_claims(claims, audience="hi-agent")


# ---------------------------------------------------------------------------
# RBAC enforcer
# ---------------------------------------------------------------------------

_POLICY = {
    "read": {"admin", "reader"},
    "write": {"admin"},
    "delete": {"admin"},
}


class TestRBACEnforcer:
    def test_admin_can_read_and_write(self):
        e = RBACEnforcer(_POLICY)
        assert e.can(role="admin", operation="read")
        assert e.can(role="admin", operation="write")

    def test_reader_can_read_not_write(self):
        e = RBACEnforcer(_POLICY)
        assert e.can(role="reader", operation="read")
        assert not e.can(role="reader", operation="write")

    def test_enforce_raises_on_deny(self):
        e = RBACEnforcer(_POLICY)
        with pytest.raises(OperationNotAllowedError):
            e.enforce(role="reader", operation="delete")

    def test_unknown_operation(self):
        e = RBACEnforcer(_POLICY)
        with pytest.raises(UnknownOperationError):
            e.can(role="admin", operation="fly")


# ---------------------------------------------------------------------------
# SOC guard
# ---------------------------------------------------------------------------

class TestSOCGuard:
    def test_different_principals_allowed(self):
        enforce_submitter_approver_separation(submitter="alice", approver="bob")

    def test_same_principal_raises(self):
        with pytest.raises(SeparationOfConcernError):
            enforce_submitter_approver_separation(submitter="alice", approver="alice")

    def test_disabled_allows_same(self):
        enforce_submitter_approver_separation(
            submitter="alice", approver="alice", enabled=False
        )
