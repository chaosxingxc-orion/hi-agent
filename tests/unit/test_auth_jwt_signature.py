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
from hi_agent.server.auth_middleware import AuthMiddleware, _verify_jwt

_SECRET = "test-secret-key-for-h5-32-bytes-ok"
_WRONG_SECRET = "wrong-secret-key-for-h5-32-bytes-ok"
_ATTACKER_SECRET = "attacker-key-for-h5-32-bytes-okay"
_FORGED_SECRET = "forged-secret-for-h5-32-bytes-ok"
_ANY_SECRET = "any-key-for-claims-mode-32-bytes-ok"
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


def _make_middleware(secret: str | None = None) -> AuthMiddleware:
    """Create an AuthMiddleware with one API key and optional JWT secret."""
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


class TestAuthMiddlewareJwtWithoutSecret:
    """Backward-compat: claims-only mode when HI_AGENT_JWT_SECRET is absent."""

    def test_valid_claims_accepted_without_secret(self) -> None:
        """JWT with valid claims passes when no secret is configured."""
        mw = _make_middleware(secret=None)
        assert mw._jwt_secret is None
        # Use any key — signature is not checked
        token = _make_token(_ANY_SECRET)
        role = mw._authenticate(token)
        assert role == "read"

    def test_expired_claims_rejected_without_secret(self) -> None:
        mw = _make_middleware(secret=None)
        token = _make_token(_ANY_SECRET, exp_offset=-10)
        role = mw._authenticate(token)
        assert role is None

    def test_wrong_audience_rejected_without_secret(self) -> None:
        mw = _make_middleware(secret=None)
        token = _make_token(_ANY_SECRET, audience="other-service")
        role = mw._authenticate(token)
        assert role is None

    def test_missing_sub_rejected_without_secret(self) -> None:
        """Token without 'sub' claim is rejected even in claims-only mode."""
        payload = {
            "aud": _AUDIENCE,
            "exp": int(time.time()) + 3600,
            "role": "read",
        }
        token = pyjwt.encode(payload, _ANY_SECRET, algorithm="HS256")
        mw = _make_middleware(secret=None)
        role = mw._authenticate(token)
        assert role is None
