"""Cross-tenant denial tests for GET /runs/{run_id}/events (SSE).

Audit finding: routes_events.py calls require_tenant_context() and scopes
the run lookup via manager.get_run(run_id, workspace=ctx).  Tenant B
requesting Tenant A's run events receives 404 (not found in that tenant's
workspace).

Layer 2 — Integration: real RunManager + real route handler.
No MagicMock on the subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_events import handle_run_events_sse
from hi_agent.server.run_manager import RunManager
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
        request.scope["tenant_context"] = self._ctx
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _NoAuthMiddleware(BaseHTTPMiddleware):
    """Strips any tenant context injection — simulates unauthenticated request."""

    async def dispatch(self, request: Request, call_next):
        return await call_next(request)


class _FakeServer:
    def __init__(self, manager: RunManager) -> None:
        self.run_manager = manager
        self.run_context_manager = None
        self.executor_factory = None
        self.artifact_registry = None
        self._feedback_store = None


def _build_app(manager: RunManager, ctx: TenantContext) -> Starlette:
    routes = [
        Route("/runs/{run_id}/events", handle_run_events_sse, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(manager)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _build_unauth_app(manager: RunManager) -> Starlette:
    """Build app with no TenantContext injected — simulates missing auth token."""
    routes = [
        Route("/runs/{run_id}/events", handle_run_events_sse, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(manager)
    app.add_middleware(_NoAuthMiddleware)
    return app


@pytest.fixture()
def manager():
    rm = RunManager()
    yield rm
    rm.shutdown()


def _create_run_for_tenant(manager: RunManager, ctx: TenantContext) -> str:
    """Create a run as tenant_a and return its run_id."""
    from hi_agent.server import routes_runs

    app = Starlette(
        routes=[Route("/runs", routes_runs.handle_create_run, methods=["POST"])]
    )
    app.state.agent_server = _FakeServer(manager)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/runs", json={"goal": "events test task"})
        assert resp.status_code in (200, 201, 202), f"create run failed: {resp.text}"
        return resp.json()["run_id"]


class TestEventsRouteCrossTenant:
    """GET /runs/{run_id}/events cross-tenant scope enforcement."""

    def test_authentication_required_without_token(self, manager):
        """Unauthenticated request (no TenantContext) must return 401."""
        app = _build_unauth_app(manager)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/runs/nonexistent-run-id/events")
            assert resp.status_code == 401, (
                f"Expected 401 for unauthenticated request, got {resp.status_code}: {resp.text}"
            )

    def test_tenant_b_cannot_access_tenant_a_run_events(self, manager):
        """Tenant B requesting Tenant A's run events must receive 404."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="sess-a")
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="sess-b")

        run_id = _create_run_for_tenant(manager, ctx_a)

        app_b = _build_app(manager, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as client_b:
            resp = client_b.get(f"/runs/{run_id}/events")
            assert resp.status_code == 404, (
                f"Expected 404 for cross-tenant event access, got {resp.status_code}: {resp.text}"
            )

    def test_events_route_scope_check_is_wired(self, manager):
        """The SSE handler must call require_tenant_context() before proceeding.

        We verify that an unauthenticated request returns 401 immediately
        (not after the stream starts), confirming the auth guard is at the top
        of the handler and not inside the async generator (which would block).

        This test is the safety net: if someone removes the guard from
        handle_run_events_sse, this test catches it via a fast 401 check.
        """
        # Unauthenticated app — no context injected.
        app = _build_unauth_app(manager)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/runs/some-run-id/events")
            # Must be 401 — not a blocking stream.
            assert resp.status_code == 401, (
                f"Expected 401 from unauthenticated SSE request, "
                f"got {resp.status_code}: {resp.text}"
            )
