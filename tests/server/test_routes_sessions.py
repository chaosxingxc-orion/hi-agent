"""Unit tests for session management route handlers.

Tests the handlers directly by building a minimal Starlette app.
No mocks — uses real SessionStore (SQLite :memory:) and real RunManager.
"""

import pytest
from hi_agent.server.routes_sessions import (
    handle_get_session_runs,
    handle_list_sessions,
    handle_patch_session,
)
from hi_agent.server.run_manager import RunManager
from hi_agent.server.session_store import SessionStore
from hi_agent.server.tenant_context import TenantContext, reset_tenant_context, set_tenant_context
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route
from starlette.testclient import TestClient


class FakeServer:
    def __init__(self, session_store, run_manager):
        self.session_store = session_store
        self.run_manager = run_manager


def make_app(session_store, run_manager, user_ctx):
    class InjectCtx(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            token = set_tenant_context(user_ctx)
            try:
                return await call_next(request)
            finally:
                reset_tenant_context(token)

    routes = [
        Route("/sessions", handle_list_sessions, methods=["GET"]),
        Route("/sessions/{session_id}/runs", handle_get_session_runs, methods=["GET"]),
        Route("/sessions/{session_id}", handle_patch_session, methods=["PATCH"]),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(InjectCtx)])
    app.state.agent_server = FakeServer(session_store, run_manager)
    return app


@pytest.fixture
def store(tmp_path):
    s = SessionStore(str(tmp_path / "sessions.db"))
    s.initialize()
    return s


@pytest.fixture
def manager():
    return RunManager(max_concurrent=2, queue_size=10)


def test_list_sessions_returns_own(store, manager):
    ctx = TenantContext(tenant_id="t1", user_id="u1", session_id="")
    sid = store.create(tenant_id="t1", user_id="u1", name="my session")
    app = make_app(store, manager, ctx)
    client = TestClient(app)
    resp = client.get("/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()["sessions"]]
    assert sid in ids


def test_list_sessions_excludes_other_user(store, manager):
    ctx = TenantContext(tenant_id="t1", user_id="u2", session_id="")
    sid = store.create(tenant_id="t1", user_id="u1")  # owned by u1, not u2
    app = make_app(store, manager, ctx)
    client = TestClient(app)
    resp = client.get("/sessions")
    ids = [s["session_id"] for s in resp.json()["sessions"]]
    assert sid not in ids


def test_get_session_runs_returns_runs(store, manager):
    ctx = TenantContext(tenant_id="t1", user_id="u1", session_id="s1")
    sid = store.create(tenant_id="t1", user_id="u1")
    # Create a run bound to that session
    ctx_with_sid = TenantContext(tenant_id="t1", user_id="u1", session_id=sid)
    run_id = manager.create_run({"goal": "test"}, workspace=ctx_with_sid).run_id
    app = make_app(store, manager, ctx)
    client = TestClient(app)
    resp = client.get(f"/sessions/{sid}/runs")
    assert resp.status_code == 200
    run_ids = [r["run_id"] for r in resp.json()["runs"]]
    assert run_id in run_ids


def test_patch_session_archive(store, manager):
    ctx = TenantContext(tenant_id="t1", user_id="u1", session_id="s1")
    sid = store.create(tenant_id="t1", user_id="u1")
    app = make_app(store, manager, ctx)
    client = TestClient(app)
    resp = client.patch(f"/sessions/{sid}", json={"status": "archived"})
    assert resp.status_code == 200
    rec = store.get_unsafe(sid)
    assert rec.status == "archived"


def test_patch_session_wrong_user_returns_404(store, manager):
    ctx = TenantContext(tenant_id="t1", user_id="u2", session_id="s2")
    sid = store.create(tenant_id="t1", user_id="u1")  # owned by u1
    app = make_app(store, manager, ctx)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.patch(f"/sessions/{sid}", json={"status": "archived"})
    assert resp.status_code == 404
