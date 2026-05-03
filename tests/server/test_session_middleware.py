"""Tests for SessionMiddleware — route-aware session auto-creation."""

import pytest
from hi_agent.server._admin_session_store import admin_get_session
from hi_agent.server.session_middleware import SessionMiddleware
from hi_agent.server.session_store import SessionStore
from hi_agent.server.tenant_context import TenantContext, set_tenant_context
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def make_app(store: SessionStore):
    """Create a test Starlette app with session middleware.

    Stack order (outermost to innermost):
    AuthMiddleware(SessionMiddleware(Starlette))

    This ensures auth context is set BEFORE session middleware runs.
    """

    async def endpoint(request: Request):
        ctx = request.scope.get("tenant_context")
        return JSONResponse({"session_id": ctx.session_id if ctx else ""})

    app = Starlette(
        routes=[
            Route("/runs", endpoint, methods=["GET", "POST"]),
            Route("/health", endpoint, methods=["GET"]),
            Route("/memory/test", endpoint, methods=["GET"]),
        ]
    )

    # Wrap with session middleware
    app = SessionMiddleware(app, session_store=store)

    # Wrap with auth context middleware (simulates auth middleware, outermost)
    class AuthMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                ctx = TenantContext(tenant_id="t1", user_id="u1")
                token = set_tenant_context(ctx)
                scope["tenant_context"] = ctx
                try:
                    await self.app(scope, receive, send)
                finally:
                    from hi_agent.server.tenant_context import reset_tenant_context

                    reset_tenant_context(token)
            else:
                await self.app(scope, receive, send)

    return AuthMiddleware(app)


@pytest.fixture
def store(tmp_path):
    s = SessionStore(str(tmp_path / "s.db"))
    s.initialize()
    return s


def test_post_runs_auto_creates_session(store):
    """POST /runs without session header should auto-create session."""
    app = make_app(store)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post("/runs", json={})
    assert resp.status_code == 200
    assert "x-session-id" in resp.headers
    sid = resp.headers["x-session-id"]
    assert admin_get_session(store, sid) is not None


def test_post_runs_uses_existing_session(store):
    """POST /runs with valid session header should use that session."""
    sid = store.create(tenant_id="t1", user_id="u1")
    app = make_app(store)
    client = TestClient(app)
    resp = client.post("/runs", json={}, headers={"X-Session-Id": sid})
    assert resp.status_code == 200


def test_post_runs_wrong_session_owner_returns_403(store):
    """POST /runs with session owned by different user should return 403."""
    sid = store.create(tenant_id="t1", user_id="u2")  # owned by u2, not u1
    app = make_app(store)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/runs", json={}, headers={"X-Session-Id": sid})
    assert resp.status_code == 403


def test_get_runs_no_header_allowed(store):
    """GET /runs without session header should be allowed (optional)."""
    app = make_app(store)
    client = TestClient(app)
    resp = client.get("/runs")
    assert resp.status_code == 200


def test_health_never_creates_session(store):
    """GET /health should bypass session middleware entirely."""
    before = len(store.list_active(tenant_id="t1", user_id="u1"))
    app = make_app(store)
    client = TestClient(app)
    client.get("/health")
    after = len(store.list_active(tenant_id="t1", user_id="u1"))
    assert after == before


def test_workspace_route_requires_session(store):
    """GET /memory/test (workspace route) without session should return 400."""
    app = make_app(store)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/memory/test")  # workspace route, no session header
    assert resp.status_code == 400
