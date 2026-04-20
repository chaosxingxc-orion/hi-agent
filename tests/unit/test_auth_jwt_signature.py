"""Unit tests for JWT signature verification in AuthMiddleware (H-5).

Covers:
- Wrong-signature tokens are rejected when HI_AGENT_JWT_SECRET is set.
- Correct HS256-signed tokens are accepted.
- Backward-compat: claims-only mode passes without a secret configured.
- Invalid/expired claims are rejected even with a valid signature.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from hi_agent.server.auth_middleware import AuthMiddleware, _verify_jwt

_SECRET = "test-secret-key-for-h5-32-bytes-minimum"
_WRONG_SECRET = "wrong-secret-key-for-h5-32-bytes-min"
_ATTACKER_SECRET = "attacker-secret-key-for-h5-32-bytes"
_FORGED_SECRET = "forged-secret-key-for-h5-32-bytes!!"
_UNVERIFIED_TEST_SECRET = "claims-only-test-secret-32-bytes-min"
_AUDIENCE = "hi-agent"


# ---------------------------------------------------------------------------
# _verify_jwt helper tests
# ---------------------------------------------------------------------------


def _make_token(
    secret: str,
    audience: str = _AUDIENCE,
    sub: str = "user1",
    role: str = "read",
    exp_offset: int = 3600,
) -> str:
    payload = {
        "sub": sub,
        "aud": audience,
        "exp": int(time.time()) + exp_offset,
        "role": role,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


class TestVerifyJwtHelper:
    """Direct tests for the _verify_jwt private function."""

    def test_valid_token_returns_claims(self) -> None:
        token = _make_token(_SECRET)
        result = _verify_jwt(token, _SECRET, _AUDIENCE)
        assert result is not None
        assert result["sub"] == "user1"
        assert result["aud"] == _AUDIENCE

    def test_wrong_secret_returns_none(self) -> None:
        token = _make_token(_SECRET)
        result = _verify_jwt(token, _WRONG_SECRET, _AUDIENCE)
        assert result is None

    def test_wrong_audience_returns_none(self) -> None:
        token = _make_token(_SECRET, audience="other-service")
        result = _verify_jwt(token, _SECRET, _AUDIENCE)
        assert result is None

    def test_expired_token_returns_none(self) -> None:
        token = _make_token(_SECRET, exp_offset=-1)
        result = _verify_jwt(token, _SECRET, _AUDIENCE)
        assert result is None

    def test_malformed_token_returns_none(self) -> None:
        result = _verify_jwt("not.a.valid.jwt.token", _SECRET, _AUDIENCE)
        assert result is None


# ---------------------------------------------------------------------------
# AuthMiddleware._authenticate tests
# ---------------------------------------------------------------------------


def _make_middleware(
    secret: str | None = None,
) -> AuthMiddleware:
    """Create an AuthMiddleware with one API key and optional JWT secret.

    The middleware is instantiated inside patch.dict so env vars are captured.
    Callers that need claims-only mode (allow_unsigned_for_tests) must set the
    env var themselves via monkeypatch or patch.dict before calling _authenticate.
    """
    mock_app = MagicMock()
    env = {"HI_AGENT_API_KEY": "test-api-key"}
    if secret is not None:
        env["HI_AGENT_JWT_SECRET"] = secret
    with patch.dict("os.environ", env, clear=False):
        return AuthMiddleware(mock_app, audience=_AUDIENCE)


class TestAuthMiddlewareJwtWithSecret:
    """Tests when HI_AGENT_JWT_SECRET is configured."""

    def test_valid_signed_token_accepted(self) -> None:
        mw = _make_middleware(secret=_SECRET)
        token = _make_token(_SECRET)
        role = mw._authenticate(token)
        assert role == "read"

    def test_valid_signed_token_write_role(self) -> None:
        mw = _make_middleware(secret=_SECRET)
        token = _make_token(_SECRET, role="write")
        role = mw._authenticate(token)
        assert role == "write"

    def test_wrong_signature_rejected(self) -> None:
        """Token with valid claims but signed with wrong key must be rejected."""
        mw = _make_middleware(secret=_SECRET)
        token = _make_token(_ATTACKER_SECRET)
        role = mw._authenticate(token)
        assert role is None

    def test_tampered_payload_rejected(self) -> None:
        """Manually constructed token with forged claims must be rejected."""
        # Build a valid-looking token but sign with a different key
        payload = {
            "sub": "admin",
            "aud": _AUDIENCE,
            "exp": int(time.time()) + 3600,
            "role": "admin",
        }
        forged_token = pyjwt.encode(payload, _FORGED_SECRET, algorithm="HS256")
        mw = _make_middleware(secret=_SECRET)
        role = mw._authenticate(forged_token)
        assert role is None

    def test_expired_token_rejected_even_with_valid_signature(self) -> None:
        mw = _make_middleware(secret=_SECRET)
        token = _make_token(_SECRET, exp_offset=-10)
        role = mw._authenticate(token)
        assert role is None

    def test_wrong_audience_rejected(self) -> None:
        mw = _make_middleware(secret=_SECRET)
        token = _make_token(_SECRET, audience="other-service")
        role = mw._authenticate(token)
        assert role is None

    def test_api_key_still_works_when_secret_set(self) -> None:
        mw = _make_middleware(secret=_SECRET)
        role = mw._authenticate("test-api-key")
        assert role == "write"


_UNSIGNED_JWT_ENV = {"HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS": "true"}


class TestAuthMiddlewareJwtWithoutSecret:
    """Backward-compat: claims-only mode when HI_AGENT_JWT_SECRET is absent.

    These tests set HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS=true to enable the
    legacy claims-only fallback path.  Production code must never set this flag.
    The env var must be active both during middleware init and during _authenticate().
    """

    def test_valid_claims_accepted_without_secret(self) -> None:
        """JWT with valid claims passes when no secret is configured (test mode)."""
        with patch.dict("os.environ", _UNSIGNED_JWT_ENV, clear=False):
            mw = _make_middleware(secret=None)
            assert mw._jwt_secret is None
            # Use any key — signature is not checked in test mode
            token = _make_token(_UNVERIFIED_TEST_SECRET)
            role = mw._authenticate(token)
        assert role == "read"

    def test_expired_claims_rejected_without_secret(self) -> None:
        with patch.dict("os.environ", _UNSIGNED_JWT_ENV, clear=False):
            mw = _make_middleware(secret=None)
            token = _make_token(_UNVERIFIED_TEST_SECRET, exp_offset=-10)
            role = mw._authenticate(token)
        assert role is None

    def test_wrong_audience_rejected_without_secret(self) -> None:
        with patch.dict("os.environ", _UNSIGNED_JWT_ENV, clear=False):
            mw = _make_middleware(secret=None)
            token = _make_token(_UNVERIFIED_TEST_SECRET, audience="other-service")
            role = mw._authenticate(token)
        assert role is None

    def test_missing_sub_rejected_without_secret(self) -> None:
        """Token without 'sub' claim is rejected even in claims-only mode."""
        payload = {
            "aud": _AUDIENCE,
            "exp": int(time.time()) + 3600,
            "role": "read",
        }
        with patch.dict("os.environ", _UNSIGNED_JWT_ENV, clear=False):
            token = pyjwt.encode(payload, _UNVERIFIED_TEST_SECRET, algorithm="HS256")
            mw = _make_middleware(secret=None)
            role = mw._authenticate(token)
        assert role is None


# ---------------------------------------------------------------------------
# H-1: New tests — unsigned JWTs rejected by default
# ---------------------------------------------------------------------------

import base64
import json


def _make_unsigned_jwt(role: str = "write", audience: str = _AUDIENCE) -> str:
    """Build an alg=none JWT (unsigned)."""
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .rstrip(b"=")
        .decode()
    )
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "sub": "attacker",
                    "role": role,
                    "aud": audience,
                    "exp": int(time.time()) + 3600,
                }
            ).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}."


class TestJWTDefaultEnforce:
    """H-1: unsigned JWTs must be rejected by default when no JWT secret is set."""

    def test_unsigned_jwt_rejected_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without the test override env var, claims-only mode must be blocked."""
        monkeypatch.setenv("HI_AGENT_API_KEY", "testkey")
        monkeypatch.delenv("HI_AGENT_JWT_SECRET", raising=False)
        monkeypatch.delenv("HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS", raising=False)
        from hi_agent.server.auth_middleware import AuthMiddleware

        middleware = AuthMiddleware(app=None, audience=_AUDIENCE)
        token = _make_unsigned_jwt(role="admin")
        result = middleware._authenticate(token)
        assert result is None, f"Unsigned JWT accepted with role={result}"

    def test_unsigned_jwt_allowed_with_test_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS=true, claims-only mode is enabled."""
        monkeypatch.setenv("HI_AGENT_API_KEY", "testkey")
        monkeypatch.delenv("HI_AGENT_JWT_SECRET", raising=False)
        monkeypatch.setenv("HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS", "true")
        from hi_agent.server.auth_middleware import AuthMiddleware

        middleware = AuthMiddleware(app=None, audience=_AUDIENCE)
        token = _make_token(_UNVERIFIED_TEST_SECRET, role="read")
        result = middleware._authenticate(token)
        assert result == "read"

    def test_forged_role_rejected_without_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An attacker cannot forge admin role when no secret is set and test flag is absent."""
        monkeypatch.setenv("HI_AGENT_API_KEY", "testkey")
        monkeypatch.delenv("HI_AGENT_JWT_SECRET", raising=False)
        monkeypatch.delenv("HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS", raising=False)
        from hi_agent.server.auth_middleware import AuthMiddleware

        middleware = AuthMiddleware(app=None, audience=_AUDIENCE)
        token = _make_unsigned_jwt(role="admin")
        result = middleware._authenticate(token)
        assert result is None
