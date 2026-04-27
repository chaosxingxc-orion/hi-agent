"""Unit tests for AuthMiddleware.auth_posture (TASK-P0-1e).

Tests cover all three posture values: ok, dev_risk_open, degraded.
AuthMiddleware is constructed directly — no running server needed.
"""

from __future__ import annotations

from hi_agent.server.auth_middleware import AuthMiddleware


def _make_middleware(runtime_mode: str) -> AuthMiddleware:
    """Return an AuthMiddleware with a no-op ASGI app."""
    return AuthMiddleware(app=lambda *a: None, runtime_mode=runtime_mode)  # type: ignore[arg-type]  expiry_wave: Wave 17


class TestAuthPostureOk:
    def test_auth_posture_ok_when_api_key_set(self, monkeypatch):
        """API key present → posture is 'ok' regardless of runtime mode."""
        monkeypatch.setenv("HI_AGENT_API_KEY", "test-secret-key")
        # Force key reload by constructing a fresh instance after env is set.
        mw = _make_middleware("prod-real")
        assert mw.auth_posture == "ok"

    def test_auth_posture_ok_in_dev_mode_with_key(self, monkeypatch):
        """API key present in dev mode → posture is still 'ok'."""
        monkeypatch.setenv("HI_AGENT_API_KEY", "dev-key")
        mw = _make_middleware("dev-smoke")
        assert mw.auth_posture == "ok"


class TestAuthPostureDevRiskOpen:
    def test_auth_posture_dev_risk_open_when_no_key_dev_mode(self, monkeypatch):
        """No API key + dev-smoke mode → posture is 'dev_risk_open'."""
        monkeypatch.delenv("HI_AGENT_API_KEY", raising=False)
        mw = _make_middleware("dev-smoke")
        assert mw.auth_posture == "dev_risk_open"

    def test_auth_posture_dev_risk_open_in_local_real(self, monkeypatch):
        """No API key + local-real mode → posture is 'dev_risk_open' (not prod)."""
        monkeypatch.delenv("HI_AGENT_API_KEY", raising=False)
        mw = _make_middleware("local-real")
        assert mw.auth_posture == "dev_risk_open"


class TestAuthPostureDegraded:
    def test_auth_posture_degraded_when_no_key_prod_mode(self, monkeypatch):
        """No API key + prod-real mode → posture is 'degraded'."""
        monkeypatch.delenv("HI_AGENT_API_KEY", raising=False)
        mw = _make_middleware("prod-real")
        assert mw.auth_posture == "degraded"


class TestToolsCall503OnDegradedAuth:
    def test_tools_call_returns_503_when_auth_degraded(self, monkeypatch):
        """HTTP POST /tools/call returns 503 when auth posture is degraded.

        With Arch-3 fail-closed: when HI_AGENT_API_KEY is absent and the
        server is in prod-real mode, AuthMiddleware rejects ALL requests at
        the middleware layer before they reach route handlers.  The body
        therefore carries the auth rejection envelope rather than the
        route-level ``{"success": False}`` shape.
        """
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        monkeypatch.setenv("HI_AGENT_ENV", "prod")
        monkeypatch.delenv("HI_AGENT_API_KEY", raising=False)

        server = AgentServer(rate_limit_rps=10000)
        # Override the posture stored at build_app() time so the handler sees "degraded".
        server.app.state.auth_posture = "degraded"

        client = TestClient(server.app, raise_server_exceptions=False)
        resp = client.post("/tools/call", json={"name": "noop", "arguments": {}})
        assert resp.status_code == 503
        body = resp.json()
        # Middleware-level rejection: error envelope rather than route-level success field.
        assert body.get("reason") == "auth_not_configured"
