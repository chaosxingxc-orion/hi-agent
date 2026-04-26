"""Cross-tenant denial tests for tools/MCP routes.

Endpoints audited:
    GET  /tools          (handle_tools_list)
    POST /tools/call     (handle_tools_call)
    GET  /mcp/tools      (handle_mcp_tools)
    GET  /mcp/tools/list (handle_mcp_tools_list)
    POST /mcp/tools/call (handle_mcp_tools_call)

Audit finding (W4-D): handle_tools_list, handle_mcp_tools, handle_mcp_tools_list,
and handle_mcp_tools_call were missing require_tenant_context() guards — fixed in
this PR.  All five handlers now return 401 for unauthenticated requests.

The tool registry is global (not per-tenant data), so cross-tenant isolation
is enforced through authentication: without a token the request is rejected.
Authenticated requests from any tenant see the same global tool list — this is
the intended capability-layer design.

Layer 2 — Integration: real route handlers, no MagicMock on subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_tools_mcp import (
    handle_mcp_tools,
    handle_mcp_tools_call,
    handle_mcp_tools_list,
    handle_tools_call,
    handle_tools_list,
)
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
    """Injects a fixed TenantContext per request."""

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


class _FakeRegistry:
    def list_names(self):
        return []

    def get(self, name):
        return None


class _FakeInvoker:
    @property
    def registry(self):
        return _FakeRegistry()


class _FakeBuilder:
    def build_invoker(self):
        return _FakeInvoker()

    def build_capability_registry(self):
        return _FakeRegistry()

    def readiness(self):
        return {}


class _FakeServer:
    def __init__(self) -> None:
        self._builder = _FakeBuilder()
        self._mcp_server = None
        self.mcp_registry = _FakeMcpRegistry()


class _FakeMcpRegistry:
    def list_servers(self):
        return []


def _build_app(ctx: TenantContext) -> Starlette:
    routes = [
        Route("/tools", handle_tools_list, methods=["GET"]),
        Route("/tools/call", handle_tools_call, methods=["POST"]),
        Route("/mcp/tools", handle_mcp_tools, methods=["GET"]),
        Route("/mcp/tools/list", handle_mcp_tools_list, methods=["GET"]),
        Route("/mcp/tools/call", handle_mcp_tools_call, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer()
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _build_unauth_app() -> Starlette:
    routes = [
        Route("/tools", handle_tools_list, methods=["GET"]),
        Route("/tools/call", handle_tools_call, methods=["POST"]),
        Route("/mcp/tools", handle_mcp_tools, methods=["GET"]),
        Route("/mcp/tools/list", handle_mcp_tools_list, methods=["GET"]),
        Route("/mcp/tools/call", handle_mcp_tools_call, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer()
    app.add_middleware(_NoAuthMiddleware)
    return app


class TestToolsRouteAuthEnforcement:
    """All tools/MCP routes must reject unauthenticated requests with 401."""

    def test_tools_list_requires_auth(self):
        """GET /tools without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/tools")
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )

    def test_tools_call_requires_auth(self):
        """POST /tools/call without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/tools/call", json={"name": "file_read", "arguments": {}})
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )

    def test_mcp_tools_requires_auth(self):
        """GET /mcp/tools without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/mcp/tools")
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )

    def test_mcp_tools_list_requires_auth(self):
        """GET /mcp/tools/list without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/mcp/tools/list")
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )

    def test_mcp_tools_call_requires_auth(self):
        """POST /mcp/tools/call without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/mcp/tools/call", json={"name": "file_read", "arguments": {}})
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )


class TestToolsRouteAuthenticatedAccess:
    """Authenticated tenants can access tools endpoints."""

    def test_authenticated_tenant_can_list_tools(self):
        """GET /tools with valid auth returns 200 with tools list."""
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-a")
        app = _build_app(ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/tools")
            assert resp.status_code == 200, (
                f"Expected 200 for authenticated tools list, got {resp.status_code}: {resp.text}"
            )
            data = resp.json()
            assert "tools" in data

    def test_authenticated_tenant_can_list_mcp_tools(self):
        """GET /mcp/tools with valid auth returns 200."""
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-a")
        app = _build_app(ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/mcp/tools")
            assert resp.status_code == 200, (
                f"Expected 200 for authenticated mcp tools, got {resp.status_code}: {resp.text}"
            )
