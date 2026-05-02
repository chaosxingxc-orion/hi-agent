"""Tenant default-fallback tests for AuthMiddleware (T-11' fix).

W31, T-11' BLOCKER: AuthMiddleware unconditionally coerced missing tenant_id
claims to ``"default"``, silently downgrading authentication identity to a
shared bucket. Under research/prod posture this masked cross-tenant access.

Behaviour now:
- research/prod posture + JWT lacking ``tenant_id`` claim → 401 (fail-closed).
- dev posture + JWT lacking ``tenant_id`` → 200 with TenantContext.tenant_id ==
  "default" and a WARNING log (back-compat).
- API-key tokens (no JWT claims) continue to use the configured fallback —
  they cannot carry a tenant_id; under strict posture API-key auth is
  expected to be paired with HI_AGENT_DEFAULT_TENANT_ID or an upstream
  reverse-proxy header that is out of scope for this gate.

Layer 2 — Integration: real AuthMiddleware against a tiny Starlette app.
"""

from __future__ import annotations

import base64
import json
import os
from unittest.mock import patch

from hi_agent.server.auth_middleware import AuthMiddleware
from hi_agent.server.tenant_context import get_tenant_context
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def _echo_endpoint(request):
    """Echo back the current TenantContext.tenant_id for verification."""
    ctx = get_tenant_context()
    return JSONResponse(
        {"ok": True, "tenant_id": ctx.tenant_id if ctx else None}
    )


def _make_app(runtime_mode: str = "dev-smoke") -> Starlette:
    app = Starlette(routes=[Route("/echo", _echo_endpoint)])
    app.add_middleware(AuthMiddleware, runtime_mode=runtime_mode)
    return app


def _build_unsigned_jwt(claims: dict) -> str:
    """Build an unsigned JWT (alg=none) carrying the given claims."""
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .rstrip(b"=")
        .decode()
    )
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    )
    return f"{header}.{payload}."


# ---------------------------------------------------------------------------
# research / prod posture: missing tenant_id claim must reject
# ---------------------------------------------------------------------------


class TestStrictPostureRejectsMissingTenantId:
    def test_research_posture_rejects_jwt_without_tenant_id(self):
        """JWT with sub/aud/exp but NO tenant_id under research → 401."""
        # exp far in the future
        claims = {
            "sub": "user-123",
            "aud": "hi-agent",
            "exp": 9999999999,
            "role": "write",
            # NOTE: no tenant_id
        }
        token = _build_unsigned_jwt(claims)
        env = {
            "HI_AGENT_API_KEY": "valid-key",
            "HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS": "true",
            "HI_AGENT_POSTURE": "research",
            "ENFORCE_JWT_SIGNATURE": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HI_AGENT_JWT_SECRET", None)
            app = _make_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/echo", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 401, (
            f"Expected 401 under research without tenant_id claim; "
            f"got {resp.status_code}: {resp.text}"
        )

    def test_prod_posture_rejects_jwt_without_tenant_id(self):
        """JWT with sub/aud/exp but NO tenant_id under prod → 401."""
        claims = {
            "sub": "user-456",
            "aud": "hi-agent",
            "exp": 9999999999,
            "role": "write",
        }
        token = _build_unsigned_jwt(claims)
        env = {
            "HI_AGENT_API_KEY": "valid-key",
            "HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS": "true",
            "HI_AGENT_POSTURE": "prod",
            "ENFORCE_JWT_SIGNATURE": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HI_AGENT_JWT_SECRET", None)
            app = _make_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/echo", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 401

    def test_research_posture_accepts_jwt_with_tenant_id(self):
        """JWT carrying tenant_id is accepted under research with that tenant."""
        claims = {
            "sub": "user-789",
            "aud": "hi-agent",
            "exp": 9999999999,
            "role": "write",
            "tenant_id": "tenant-A",
        }
        token = _build_unsigned_jwt(claims)
        env = {
            "HI_AGENT_API_KEY": "valid-key",
            "HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS": "true",
            "HI_AGENT_POSTURE": "research",
            "ENFORCE_JWT_SIGNATURE": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HI_AGENT_JWT_SECRET", None)
            app = _make_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/echo", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "tenant-A"


# ---------------------------------------------------------------------------
# dev posture: missing tenant_id claim falls back to "default" with WARNING
# ---------------------------------------------------------------------------


class TestDevPostureFallsBackToDefault:
    def test_dev_posture_uses_default_tenant_id_with_warning(self, caplog):
        """JWT without tenant_id under dev → 200 + tenant_id="default" + WARNING."""
        claims = {
            "sub": "user-dev",
            "aud": "hi-agent",
            "exp": 9999999999,
            "role": "write",
        }
        token = _build_unsigned_jwt(claims)
        env = {
            "HI_AGENT_API_KEY": "valid-key",
            "HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS": "true",
            "HI_AGENT_POSTURE": "dev",
            "ENFORCE_JWT_SIGNATURE": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HI_AGENT_JWT_SECRET", None)
            app = _make_app()
            client = TestClient(app, raise_server_exceptions=False)
            with caplog.at_level("WARNING"):
                resp = client.get(
                    "/echo", headers={"Authorization": f"Bearer {token}"}
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == "default"
        # WARNING log mentioning tenant_id fallback emitted.
        warning_messages = [
            rec.message for rec in caplog.records if rec.levelname == "WARNING"
        ]
        assert any(
            "tenant_id" in msg.lower() and "default" in msg.lower()
            for msg in warning_messages
        ), (
            f"Expected WARNING about tenant_id fallback to default; "
            f"got: {warning_messages}"
        )

    def test_dev_posture_with_tenant_id_uses_claim(self):
        """JWT with tenant_id under dev → 200 + that tenant_id."""
        claims = {
            "sub": "user-dev2",
            "aud": "hi-agent",
            "exp": 9999999999,
            "role": "write",
            "tenant_id": "tenant-X",
        }
        token = _build_unsigned_jwt(claims)
        env = {
            "HI_AGENT_API_KEY": "valid-key",
            "HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS": "true",
            "HI_AGENT_POSTURE": "dev",
            "ENFORCE_JWT_SIGNATURE": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HI_AGENT_JWT_SECRET", None)
            app = _make_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/echo", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "tenant-X"
