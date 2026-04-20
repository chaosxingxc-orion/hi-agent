"""Tests that run route handlers enforce workspace ownership.

Layer 3 (E2E via HTTP): drives the public HTTP interface with a real RunManager
and two distinct user contexts to verify cross-user isolation.

No mocks are used — real RunManager, real TenantContext.
"""
from __future__ import annotations

import pytest
from hi_agent.server import routes_runs
from hi_agent.server.run_manager import RunManager
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(user_id: str, session_id: str, tenant_id: str = "t1") -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id)


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a TenantContext into every request for testing."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request, call_next):
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _FakeServer:
    """Minimal stand-in for AgentServer used by route handlers."""

    def __init__(self, manager: RunManager) -> None:
        self.run_manager = manager
        self.run_context_manager = None
        self.executor_factory = None
        self.artifact_registry = None


def _build_app(server: _FakeServer, ctx: TenantContext) -> Starlette:
    """Build a Starlette app with run routes and an injected TenantContext."""
    routes = [
        Route("/runs", routes_runs.handle_list_runs, methods=["GET"]),
        Route("/runs", routes_runs.handle_create_run, methods=["POST"]),
        Route("/runs/{run_id}", routes_runs.handle_get_run, methods=["GET"]),
        Route("/runs/{run_id}/signal", routes_runs.handle_signal_run, methods=["POST"]),
        Route("/runs/{run_id}/artifacts", routes_runs.handle_run_artifacts, methods=["GET"]),
    ]
    app = Starlette(
        routes=routes,
        middleware=[Middleware(_InjectCtxMiddleware, ctx=ctx)],
    )
    app.state.agent_server = server
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def two_user_setup():
    """Create a RunManager with one run owned by user A.

    Returns (manager, run_id_a, ctx_a, ctx_b).
    """
    manager = RunManager(max_concurrent=2, queue_size=10)
    ctx_a = _make_ctx(user_id="u1", session_id="s1")
    ctx_b = _make_ctx(user_id="u2", session_id="s2")
    run_id = manager.create_run({"goal": "user a task"}, workspace=ctx_a)
    return manager, run_id, ctx_a, ctx_b


# ---------------------------------------------------------------------------
# Tests — workspace isolation
# ---------------------------------------------------------------------------

def test_get_run_cross_user_returns_404(two_user_setup):
    """User B cannot GET a run owned by User A."""
    manager, run_id, _ctx_a, ctx_b = two_user_setup
    server = _FakeServer(manager)
    client = TestClient(_build_app(server, ctx_b), raise_server_exceptions=False)

    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 404


def test_get_run_owner_returns_200(two_user_setup):
    """User A can GET their own run."""
    manager, run_id, ctx_a, _ctx_b = two_user_setup
    server = _FakeServer(manager)
    client = TestClient(_build_app(server, ctx_a), raise_server_exceptions=False)

    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == run_id


def test_list_runs_does_not_show_other_users_run(two_user_setup):
    """User B's GET /runs must not contain User A's run."""
    manager, run_id, _ctx_a, ctx_b = two_user_setup
    server = _FakeServer(manager)
    client = TestClient(_build_app(server, ctx_b), raise_server_exceptions=False)

    resp = client.get("/runs")
    assert resp.status_code == 200
    run_ids = [r["run_id"] for r in resp.json().get("runs", [])]
    assert run_id not in run_ids


def test_list_runs_shows_own_run(two_user_setup):
    """User A's GET /runs contains their own run."""
    manager, run_id, ctx_a, _ctx_b = two_user_setup
    server = _FakeServer(manager)
    client = TestClient(_build_app(server, ctx_a), raise_server_exceptions=False)

    resp = client.get("/runs")
    assert resp.status_code == 200
    run_ids = [r["run_id"] for r in resp.json().get("runs", [])]
    assert run_id in run_ids


def test_signal_run_cross_user_returns_404(two_user_setup):
    """User B cannot cancel a run owned by User A."""
    manager, run_id, _ctx_a, ctx_b = two_user_setup
    server = _FakeServer(manager)
    client = TestClient(_build_app(server, ctx_b), raise_server_exceptions=False)

    resp = client.post(f"/runs/{run_id}/signal", json={"signal": "cancel"})
    assert resp.status_code == 404


def test_artifacts_cross_user_returns_404(two_user_setup):
    """User B cannot fetch artifacts for User A's run."""
    manager, run_id, _ctx_a, ctx_b = two_user_setup
    server = _FakeServer(manager)
    client = TestClient(_build_app(server, ctx_b), raise_server_exceptions=False)

    resp = client.get(f"/runs/{run_id}/artifacts")
    assert resp.status_code == 404


def test_no_tenant_context_returns_401(two_user_setup):
    """Requests without TenantContext return 401."""
    manager, run_id, _ctx_a, _ctx_b = two_user_setup
    server = _FakeServer(manager)

    # Build app WITHOUT the InjectCtxMiddleware — no context will be set.
    routes = [
        Route("/runs", routes_runs.handle_list_runs, methods=["GET"]),
        Route("/runs/{run_id}", routes_runs.handle_get_run, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = server
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/runs")
    assert resp.status_code == 401

    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 401


def test_create_run_binds_to_caller_workspace(two_user_setup):
    """A run created by User B is not visible to User A."""
    manager, _run_id_a, ctx_a, ctx_b = two_user_setup
    server = _FakeServer(manager)

    # User B creates a run.
    client_b = TestClient(_build_app(server, ctx_b), raise_server_exceptions=False)
    resp = client_b.post("/runs", json={"goal": "user b task"})
    assert resp.status_code == 201
    run_id_b = resp.json()["run_id"]

    # User A cannot see User B's run.
    client_a = TestClient(_build_app(server, ctx_a), raise_server_exceptions=False)
    resp = client_a.get(f"/runs/{run_id_b}")
    assert resp.status_code == 404
