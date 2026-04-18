"""Unit tests for AuthMiddleware.auth_posture (TASK-P0-1e).

Tests cover all three posture values: ok, dev_risk_open, degraded.
AuthMiddleware is constructed directly — no running server needed.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from hi_agent.server.auth_middleware import AuthMiddleware


def _make_middleware(runtime_mode: str) -> AuthMiddleware:
    """Return an AuthMiddleware with a no-op ASGI app."""
    return AuthMiddleware(app=lambda *a: None, runtime_mode=runtime_mode)  # type: ignore[arg-type]


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
