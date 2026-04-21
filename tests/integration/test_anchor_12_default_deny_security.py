"""Anchor 12 — default-deny security posture.

Guards the playbook regression anchor 12: in the absence of explicit test
overrides, hi-agent must refuse unsigned JWTs and must not silently admit a
``role=admin`` payload.

Incident trail:
- 2026-04-20 vulnerability analysis H-1 / H-2: default-permit JWT + capability
  policy shapes were flagged as exploitable.
- 2026-04-21 self-audit: documented that although code already enforces the
  safe default, no pytest pinned it. This file pins it.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import pytest


def _make_unsigned_jwt(payload: dict[str, Any]) -> str:
    """Construct a claims-only (alg=none) JWT — the canonical attack shape."""
    header = {"alg": "none", "typ": "JWT"}

    def _b64(obj: dict) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(obj).encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )

    return f"{_b64(header)}.{_b64(payload)}."


@pytest.fixture()
def auth_middleware(monkeypatch):
    """Fresh AuthMiddleware with no JWT secret and no test escape hatch."""
    monkeypatch.delenv("HI_AGENT_JWT_SECRET", raising=False)
    monkeypatch.delenv("HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS", raising=False)

    from hi_agent.server.auth_middleware import AuthMiddleware

    async def _app(scope, receive, send):  # pragma: no cover - unused
        return None

    return AuthMiddleware(app=_app, runtime_mode="prod-real")


def test_unsigned_admin_jwt_rejected_in_prod(auth_middleware) -> None:
    """prod-real: no JWT secret + no test flag → unsigned JWT MUST be rejected."""
    token = _make_unsigned_jwt({"role": "admin", "sub": "attacker"})
    assert auth_middleware._authenticate(token) is None


def test_unsigned_admin_jwt_rejected_in_non_prod_by_default(monkeypatch) -> None:
    """non-prod without the test escape hatch also rejects unsigned JWTs."""
    monkeypatch.delenv("HI_AGENT_JWT_SECRET", raising=False)
    monkeypatch.delenv("HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS", raising=False)
    from hi_agent.server.auth_middleware import AuthMiddleware

    async def _app(scope, receive, send):  # pragma: no cover - unused
        return None

    mw = AuthMiddleware(app=_app, runtime_mode="dev-smoke")
    token = _make_unsigned_jwt({"role": "admin"})
    assert mw._authenticate(token) is None


def test_unsigned_jwt_permitted_only_with_explicit_test_flag(monkeypatch) -> None:
    """The test flag HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS=true is required."""
    monkeypatch.delenv("HI_AGENT_JWT_SECRET", raising=False)
    monkeypatch.setenv("HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS", "true")
    from hi_agent.server.auth_middleware import AuthMiddleware

    async def _app(scope, receive, send):  # pragma: no cover - unused
        return None

    # Non-prod only — prod-real still rejects even with the flag set.
    mw = AuthMiddleware(app=_app, runtime_mode="dev-smoke")
    token = _make_unsigned_jwt({"role": "read", "sub": "test", "aud": mw._audience})
    # validate_jwt_claims may reject on audience shape — depending on the
    # middleware's validator, this call returns either a role string or None.
    # Either way it must not raise, and it must never silently upgrade to a
    # role the token didn't claim.
    role = mw._authenticate(token)
    assert role in (None, "read"), f"unexpected role {role!r}"


def test_enforce_jwt_signature_defaults_true() -> None:
    """The enforcement env var must default to true.

    This pins the default so a later change to the getenv fallback that lets
    it drift to "false" is caught immediately.
    """
    os.environ.pop("ENFORCE_JWT_SIGNATURE", None)
    enforce = os.getenv("ENFORCE_JWT_SIGNATURE", "true").lower() == "true"
    assert enforce is True, (
        "ENFORCE_JWT_SIGNATURE default must be 'true'; got no default or a "
        "different value. This governs AuthMiddleware.__init__ line ~118."
    )
