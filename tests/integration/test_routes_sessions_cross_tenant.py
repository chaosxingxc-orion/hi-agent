"""Cross-tenant isolation integration tests for session routes (W5-G).

Verifies that Tenant B cannot list, read, or modify Tenant A's sessions.

Layer 2 — Integration: real SessionStore + real route handlers.
No MagicMock on the subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server import routes_sessions
from hi_agent.server.run_manager import RunManager
from hi_agent.server.session_store import SessionStore
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


class _FakeServer:
    """Minimal stand-in for AgentServer used by session route handlers."""

    def __init__(self, store: SessionStore, manager: RunManager) -> None:
        self.session_store = store
        self.run_manager = manager


def _build_app(store: SessionStore, manager: RunManager, ctx: TenantContext) -> Starlette:
    """Build a minimal ASGI app with session routes and injected TenantContext."""
    app_routes = [
        Route("/sessions", routes_sessions.handle_list_sessions, methods=["GET"]),
        Route(
            "/sessions/{session_id}/runs",
            routes_sessions.handle_get_session_runs,
            methods=["GET"],
        ),
        Route(
            "/sessions/{session_id}",
            routes_sessions.handle_patch_session,
            methods=["PATCH"],
        ),
    ]
    app = Starlette(routes=app_routes)
    app.state.agent_server = _FakeServer(store, manager)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrossTenantSessionIsolation:
    """Session route cross-tenant access denial."""

    @pytest.fixture()
    def store(self):
        s = SessionStore(db_path=":memory:")
        s.initialize()
        return s

    @pytest.fixture()
    def manager(self):
        rm = RunManager()
        yield rm
        rm.shutdown()

    @pytest.fixture()
    def session_a(self, store) -> str:
        """Create a session owned by tenant-A, return its session_id."""
        return store.create(
            tenant_id="tenant-A",
            user_id="user-a",
            name="session-A-private",
        )

    def test_tenant_b_list_does_not_see_tenant_a_sessions(self, store, manager, session_a):
        """GET /sessions for Tenant B must not return Tenant A's sessions."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")
        app = _build_app(store, manager, ctx_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/sessions")
        assert resp.status_code == 200
        session_ids = [s.get("session_id") for s in resp.json().get("sessions", [])]
        assert session_a not in session_ids, (
            f"Tenant B's session list leaked Tenant A's session_id={session_a}"
        )

    def test_tenant_a_can_list_own_sessions(self, store, manager, session_a):
        """GET /sessions for Tenant A returns its own sessions."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
        app = _build_app(store, manager, ctx_a)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/sessions")
        assert resp.status_code == 200
        session_ids = [s.get("session_id") for s in resp.json().get("sessions", [])]
        assert session_a in session_ids, (
            f"Tenant A's own session_id={session_a} not returned in list"
        )

    def test_tenant_b_cannot_get_tenant_a_session_runs(self, store, manager, session_a):
        """GET /sessions/{session_id}/runs from Tenant B on Tenant A's session → 404."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")
        app = _build_app(store, manager, ctx_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/sessions/{session_a}/runs")
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant session runs, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_a_can_get_own_session_runs(self, store, manager, session_a):
        """GET /sessions/{session_id}/runs from Tenant A on its own session → 200."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
        app = _build_app(store, manager, ctx_a)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/sessions/{session_a}/runs")
        assert resp.status_code == 200, (
            f"Expected 200 for same-tenant session runs, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_b_cannot_archive_tenant_a_session(self, store, manager, session_a):
        """PATCH /sessions/{session_id} from Tenant B on Tenant A's session → 404."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")
        app = _build_app(store, manager, ctx_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(
                f"/sessions/{session_a}",
                json={"status": "archived"},
            )
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant session archive, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_a_can_archive_own_session(self, store, manager, session_a):
        """PATCH /sessions/{session_id} from Tenant A on its own session → 200."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
        app = _build_app(store, manager, ctx_a)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(
                f"/sessions/{session_a}",
                json={"status": "archived"},
            )
        assert resp.status_code == 200, (
            f"Expected 200 for same-tenant session archive, got {resp.status_code}: {resp.text}"
        )
