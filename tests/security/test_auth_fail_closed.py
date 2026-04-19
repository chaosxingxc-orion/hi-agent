"""Security tests for AuthMiddleware fail-closed behaviour (Arch-3).

Covers three scenarios:
1. prod-real mode + no API key configured  → 503 (fail-closed)
2. dev-smoke mode + no API key configured  → passthrough (backward compat)
3. prod-real mode + API key configured      → normal 200 operation

Layer 1 — Unit: exercises the ASGI __call__ path directly; no running server.
No external I/O; uses a trivial ASGI echo-app as the inner application.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import jwt as pyjwt
import pytest

from hi_agent.server.auth_middleware import AuthMiddleware


# ---------------------------------------------------------------------------
# ASGI test harness
# ---------------------------------------------------------------------------

_CAPTURED: dict[str, Any] = {}


async def _capture_app(scope: Any, receive: Any, send: Any) -> None:
    """Inner app that records that it was reached and sends a 200."""
    _CAPTURED["reached"] = True
    _CAPTURED["scope"] = scope
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        }
    )
    await send({"type": "http.response.body", "body": b"ok"})


class _FakeSend:
    """Collect response events sent by the middleware."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    @property
    def status(self) -> int | None:
        for e in self.events:
            if e.get("type") == "http.response.start":
                return e["status"]
        return None


async def _fake_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b""}


def _make_scope(path: str = "/runs", method: str = "GET") -> dict[str, Any]:
    return {
        "type": "http",
        "path": path,
        "method": method,
        "headers": [],
        "client": ("127.0.0.1", 9999),
    }


def _scope_with_bearer(token: str, path: str = "/runs") -> dict[str, Any]:
    scope = _make_scope(path=path)
    scope["headers"] = [
        (b"authorization", f"Bearer {token}".encode()),
    ]
    return scope


def _make_jwt(sub: str = "user-1", role: str = "read", exp_offset: int = 3600) -> str:
    payload = {
        "sub": sub,
        "aud": "hi-agent",
        "exp": int(time.time()) + exp_offset,
        "role": role,
    }
    # Sign with a dummy key — in tests without HI_AGENT_JWT_SECRET the
    # middleware runs in claims-only mode, so the signature is irrelevant.
    return pyjwt.encode(payload, "test-secret", algorithm="HS256")


# ---------------------------------------------------------------------------
# Scenario 1: prod-real + no API key → 503
# ---------------------------------------------------------------------------


class TestProdRealFailClosed:
    """AuthMiddleware must return 503 for all requests in prod-real mode
    when HI_AGENT_API_KEY is not configured."""

    @pytest.mark.asyncio
    async def test_no_key_prod_real_returns_503(self) -> None:
        with patch.dict("os.environ", {"HI_AGENT_API_KEY": ""}, clear=False):
            mw = AuthMiddleware(_capture_app, runtime_mode="prod-real")

        assert mw.auth_posture == "degraded"

        _CAPTURED.clear()
        sender = _FakeSend()
        await mw(_make_scope(), _fake_receive, sender)

        assert sender.status == 503, f"Expected 503, got {sender.status}"
        assert not _CAPTURED.get("reached"), "Inner app must not be reached"

    @pytest.mark.asyncio
    async def test_no_key_prod_real_returns_503_for_write(self) -> None:
        """POST also blocked when no key in prod-real."""
        with patch.dict("os.environ", {"HI_AGENT_API_KEY": ""}, clear=False):
            mw = AuthMiddleware(_capture_app, runtime_mode="prod-real")

        _CAPTURED.clear()
        sender = _FakeSend()
        await mw(_make_scope(method="POST"), _fake_receive, sender)

        assert sender.status == 503

    @pytest.mark.asyncio
    async def test_exempt_health_path_not_affected(self) -> None:
        """/health bypasses auth entirely — even in prod-real without key."""
        with patch.dict("os.environ", {"HI_AGENT_API_KEY": ""}, clear=False):
            mw = AuthMiddleware(_capture_app, runtime_mode="prod-real")

        # Exempt paths are checked BEFORE the fail-closed gate so /health is
        # always reachable regardless of whether an API key is configured.
        sender = _FakeSend()
        _CAPTURED.clear()
        await mw(_make_scope(path="/health"), _fake_receive, sender)
        assert sender.status == 200


# ---------------------------------------------------------------------------
# Scenario 2: dev-smoke + no API key → passthrough
# ---------------------------------------------------------------------------


class TestDevSmokePassthrough:
    """When runtime_mode != 'prod-real', missing API key is backward compat."""

    @pytest.mark.asyncio
    async def test_no_key_dev_smoke_passes_through(self) -> None:
        with patch.dict("os.environ", {"HI_AGENT_API_KEY": ""}, clear=False):
            mw = AuthMiddleware(_capture_app, runtime_mode="dev-smoke")

        assert mw.auth_posture == "dev_risk_open"

        _CAPTURED.clear()
        sender = _FakeSend()
        await mw(_make_scope(), _fake_receive, sender)

        assert sender.status == 200, f"Expected 200 passthrough, got {sender.status}"
        assert _CAPTURED.get("reached") is True

    @pytest.mark.asyncio
    async def test_no_key_no_mode_defaults_dev_behaviour(self) -> None:
        """Default runtime_mode is 'dev-smoke', so no key → passthrough."""
        with patch.dict("os.environ", {"HI_AGENT_API_KEY": ""}, clear=False):
            mw = AuthMiddleware(_capture_app)  # default runtime_mode="dev-smoke"

        _CAPTURED.clear()
        sender = _FakeSend()
        await mw(_make_scope(), _fake_receive, sender)

        assert sender.status == 200


# ---------------------------------------------------------------------------
# Scenario 3: prod-real + API key configured → normal operation
# ---------------------------------------------------------------------------


class TestProdRealWithKey:
    """When an API key is configured, prod-real behaves normally (auth enforced)."""

    _API_KEY = "secure-prod-key-123"

    def _make_mw(self) -> AuthMiddleware:
        with patch.dict(
            "os.environ", {"HI_AGENT_API_KEY": self._API_KEY}, clear=False
        ):
            return AuthMiddleware(_capture_app, runtime_mode="prod-real")

    @pytest.mark.asyncio
    async def test_valid_api_key_returns_200(self) -> None:
        mw = self._make_mw()
        assert mw.auth_posture == "ok"

        _CAPTURED.clear()
        sender = _FakeSend()
        scope = _scope_with_bearer(self._API_KEY)
        await mw(scope, _fake_receive, sender)

        assert sender.status == 200
        assert _CAPTURED.get("reached") is True

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self) -> None:
        mw = self._make_mw()
        _CAPTURED.clear()
        sender = _FakeSend()
        await mw(_make_scope(), _fake_receive, sender)
        assert sender.status == 401
        assert not _CAPTURED.get("reached")

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self) -> None:
        mw = self._make_mw()
        _CAPTURED.clear()
        sender = _FakeSend()
        await mw(_scope_with_bearer("wrong-key"), _fake_receive, sender)
        assert sender.status == 401

    @pytest.mark.asyncio
    async def test_tenant_context_set_after_successful_auth(self) -> None:
        """After a successful API-key auth the scope carries tenant_context."""
        mw = self._make_mw()
        _CAPTURED.clear()
        sender = _FakeSend()
        scope = _scope_with_bearer(self._API_KEY)
        await mw(scope, _fake_receive, sender)

        assert sender.status == 200
        tc = _CAPTURED["scope"].get("tenant_context")
        assert tc is not None, "tenant_context must be stored in ASGI scope"
        assert tc.auth_method == "api_key"
        assert tc.roles == ["write"]
        assert tc.tenant_id == "default"
