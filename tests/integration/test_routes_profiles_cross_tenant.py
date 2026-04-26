"""Cross-tenant denial tests for profile routes.

Endpoints:
    GET /profiles/hi_agent_global/memory/l3
    GET /profiles/hi_agent_global/skills

Audit finding: routes_profiles.py requires:
    1. Authentication (require_tenant_context → 401 without token).
    2. Admin privilege (is_admin or tenant_id == "admin" → 403 for non-admin).

Non-admin tenants receive 403 from profile global routes.
Unauthenticated requests receive 401.

Layer 2 — Integration: real route handlers, no MagicMock on subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_profiles import handle_global_l3_summary, handle_global_skills
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext per request (bypasses AuthMiddleware)."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request: Request, call_next):
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _NoAuthMiddleware(BaseHTTPMiddleware):
    """Strips tenant context — simulates unauthenticated request."""

    async def dispatch(self, request: Request, call_next):
        return await call_next(request)


def _build_app(ctx: TenantContext) -> Starlette:
    routes = [
        Route("/profiles/hi_agent_global/memory/l3", handle_global_l3_summary, methods=["GET"]),
        Route("/profiles/hi_agent_global/skills", handle_global_skills, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    # No agent_server needed; handler falls back to ProfileDirectoryManager default.
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _build_unauth_app() -> Starlette:
    routes = [
        Route("/profiles/hi_agent_global/memory/l3", handle_global_l3_summary, methods=["GET"]),
        Route("/profiles/hi_agent_global/skills", handle_global_skills, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(_NoAuthMiddleware)
    return app


class TestProfileRouteCrossTenant:
    """Profile global routes: auth + admin scope enforcement."""

    def test_authentication_required_for_l3_summary(self):
        """GET /profiles/hi_agent_global/memory/l3 without auth must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/profiles/hi_agent_global/memory/l3")
            assert resp.status_code == 401, (
                f"Expected 401 for unauthenticated l3 summary, got {resp.status_code}: {resp.text}"
            )

    def test_authentication_required_for_skills(self):
        """GET /profiles/hi_agent_global/skills without auth must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/profiles/hi_agent_global/skills")
            assert resp.status_code == 401, (
                f"Expected 401 for unauthenticated skills, got {resp.status_code}: {resp.text}"
            )

    def test_non_admin_tenant_is_denied_l3_summary(self):
        """Non-admin tenant accessing global profile routes must receive 403."""
        ctx = TenantContext(tenant_id="tenant-regular", user_id="user-regular")
        app = _build_app(ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/profiles/hi_agent_global/memory/l3")
            assert resp.status_code == 403, (
                f"Expected 403 for non-admin l3 summary, got {resp.status_code}: {resp.text}"
            )

    def test_non_admin_tenant_is_denied_skills(self):
        """Non-admin tenant accessing global skills must receive 403."""
        ctx = TenantContext(tenant_id="tenant-regular", user_id="user-regular")
        app = _build_app(ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/profiles/hi_agent_global/skills")
            assert resp.status_code == 403, (
                f"Expected 403 for non-admin skills, got {resp.status_code}: {resp.text}"
            )

    def test_admin_tenant_is_allowed_l3_summary(self):
        """Tenant with tenant_id == 'admin' is permitted to access global profile routes."""
        ctx = TenantContext(tenant_id="admin", user_id="admin-user")
        app = _build_app(ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/profiles/hi_agent_global/memory/l3")
            # Route may return 200 (profile exists) or 503 (manager unavailable),
            # but must not return 401 or 403.
            assert resp.status_code not in (401, 403), (
                f"Admin must not be denied, got {resp.status_code}: {resp.text}"
            )
