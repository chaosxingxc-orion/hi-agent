"""Acceptance tests 1-10: run and event ownership isolation.

Uses real RunManager + SessionStore + route handlers.
No cross-user or cross-session data leakage allowed.

Auth approach: custom _InjectCtxMiddleware bypasses AuthMiddleware and
injects a real TenantContext directly (Option 2 from the task spec).
This gives full workspace isolation without requiring JWT setup.

For tests 6-7 that must exercise the real AuthMiddleware, we spin up an
AgentServer with HI_AGENT_API_KEY set in the environment.
"""

from __future__ import annotations

import os

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hi_agent.server import routes_events, routes_runs
from hi_agent.server.run_manager import RunManager
from hi_agent.server.session_middleware import SessionMiddleware
from hi_agent.server.session_store import SessionStore
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(user_id: str, session_id: str, tenant_id: str = "t1") -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id)


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext for every request (bypasses AuthMiddleware)."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request, call_next):
        # Propagate to scope so SessionMiddleware can find it via scope lookup.
        request.scope["tenant_context"] = self._ctx
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
        self._feedback_store = None


def _build_isolation_app(
    manager: RunManager,
    ctx: TenantContext,
    session_store: SessionStore | None = None,
):
    """Build an ASGI app with run + event routes and an injected TenantContext.

    Middleware stack (outermost to innermost):
        _RawInjectCtxMiddleware  — sets TenantContext on ContextVar + scope
        SessionMiddleware        — validates/creates sessions (reads ctx from scope)
        Starlette                — route handlers

    When session_store is None, SessionMiddleware is omitted.
    """
    fake_server = _FakeServer(manager)

    routes = [
        Route("/runs", routes_runs.handle_list_runs, methods=["GET"]),
        Route("/runs", routes_runs.handle_create_run, methods=["POST"]),
        Route("/runs/{run_id}", routes_runs.handle_get_run, methods=["GET"]),
        Route("/runs/{run_id}/signal", routes_runs.handle_signal_run, methods=["POST"]),
        Route("/runs/{run_id}/events", routes_events.handle_run_events_sse, methods=["GET"]),
        Route("/health", _health_handler, methods=["GET"]),
    ]

    inner = Starlette(routes=routes)
    inner.state.agent_server = fake_server

    # Optionally wrap inner with SessionMiddleware
    if session_store is not None:
        mid: object = SessionMiddleware(inner, session_store=session_store)
    else:
        mid = inner

    # Outermost: raw ASGI context injector (sets ctx BEFORE SessionMiddleware)
    return _RawInjectCtxMiddleware(mid, ctx=ctx, starlette_state=inner.state)


async def _health_handler(request: Request) -> JSONResponse:
    """Minimal /health handler for test 9."""
    return JSONResponse({"status": "ok"})


class _RawInjectCtxMiddleware:
    """Raw ASGI middleware that injects a TenantContext before any other middleware.

    Sets ctx on both the ContextVar and scope["tenant_context"] so that
    SessionMiddleware can find it via scope lookup (which it does before the
    ContextVar path).

    Exposes ``state`` so TestClient construction does not break on attribute
    access patterns used by some fixtures.
    """

    def __init__(self, app, ctx: TenantContext, starlette_state) -> None:
        self._app = app
        self._ctx = ctx
        self.state = starlette_state

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Make a copy of ctx per request so mutation (e.g. session_id set
            # by SessionMiddleware) is local to this request invocation.
            import copy
            req_ctx = copy.copy(self._ctx)
            scope["tenant_context"] = req_ctx
            token = set_tenant_context(req_ctx)
            try:
                await self._app(scope, receive, send)
            finally:
                reset_tenant_context(token)
        else:
            await self._app(scope, receive, send)


def session_count(store: SessionStore) -> int:
    """Count the number of active sessions in the store (all tenants/users).

    Uses the public list_active API scoped to the known test tenant so we
    avoid touching the private _cx() connection handle.
    """
    # Test fixture only ever creates sessions under tenant "t1"; counting
    # active sessions for an empty user_id string is not supported, so we
    # query both test user accounts and sum.
    return len(store.list_active("t1", "user_a")) + len(store.list_active("t1", "user_b"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def shared_manager():
    """RunManager shared between user A and user B."""
    return RunManager(max_concurrent=2, queue_size=10)


@pytest.fixture()
def ctx_a():
    return _make_ctx(user_id="user_a", session_id="session_a")


@pytest.fixture()
def ctx_b():
    return _make_ctx(user_id="user_b", session_id="session_b")


@pytest.fixture()
def client_a(shared_manager, ctx_a):
    """TestClient authenticated as user A."""
    app = _build_isolation_app(shared_manager, ctx_a)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def client_b(shared_manager, ctx_b):
    """TestClient authenticated as user B."""
    app = _build_isolation_app(shared_manager, ctx_b)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def user_a_run(shared_manager, ctx_a):
    """Create a run owned by user A and return (session_id, run_id)."""
    run_id = shared_manager.create_run({"goal": "user a task"}, workspace=ctx_a)
    return (ctx_a.session_id, run_id)


@pytest.fixture()
def session_store(tmp_path):
    """In-memory SQLite SessionStore for tests that exercise sessions."""
    store = SessionStore(str(tmp_path / "sessions.db"))
    store.initialize()
    return store


@pytest.fixture()
def app(shared_manager, ctx_a):
    """The Starlette app instance (for tests that need it directly)."""
    return _build_isolation_app(shared_manager, ctx_a)


# ---------------------------------------------------------------------------
# Test 1: User B cannot list User A's runs
# ---------------------------------------------------------------------------


def test_1_user_b_cannot_list_user_a_runs(client_a, client_b, user_a_run):
    """User B's GET /runs must not include runs owned by User A."""
    _, run_id = user_a_run
    resp = client_b.get("/runs")
    assert resp.status_code == 200
    run_ids = [r["run_id"] for r in resp.json().get("runs", [])]
    assert run_id not in run_ids


# ---------------------------------------------------------------------------
# Test 2: User B GET /runs/{id} for User A's run → 404
# ---------------------------------------------------------------------------


def test_2_user_b_get_run_returns_404(client_b, user_a_run):
    """User B must receive 404 when fetching a run owned by User A."""
    _, run_id = user_a_run
    resp = client_b.get(f"/runs/{run_id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 3: User B cannot cancel User A's run → 404
# ---------------------------------------------------------------------------


def test_3_user_b_cannot_cancel_user_a_run(client_b, user_a_run):
    """User B must receive 404 when attempting to cancel User A's run."""
    _, run_id = user_a_run
    resp = client_b.post(f"/runs/{run_id}/signal", json={"signal": "cancel"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 4: User B cannot signal User A's run → 404
# ---------------------------------------------------------------------------


def test_4_user_b_cannot_signal_user_a_run(client_b, user_a_run):
    """User B must receive 404 when attempting to pause User A's run."""
    _, run_id = user_a_run
    resp = client_b.post(f"/runs/{run_id}/signal", json={"signal": "pause"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 5: User B cannot connect to User A's SSE stream → 404
# ---------------------------------------------------------------------------


def test_5_user_b_cannot_connect_to_user_a_sse(client_b, user_a_run):
    """User B must receive 404 when connecting to User A's SSE stream."""
    _, run_id = user_a_run
    resp = client_b.get(f"/runs/{run_id}/events")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 6: Missing user_id (no auth) returns 401
# ---------------------------------------------------------------------------


def test_6_missing_user_id_returns_401(monkeypatch, tmp_path):
    """Requests without authentication must return 401.

    Spins up an AgentServer with HI_AGENT_API_KEY set so AuthMiddleware
    is enabled, then makes a bare request without Authorization header.
    """
    from hi_agent.server.app import AgentServer

    monkeypatch.setenv("HI_AGENT_API_KEY", "test-key-for-isolation-test-6")
    # Rebuild server inside the monkeypatched env so AuthMiddleware picks it up.
    server = AgentServer(rate_limit_rps=10000)
    client = TestClient(server.app, raise_server_exceptions=False)
    resp = client.get("/runs")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 7: Forged unsigned JWT rejected (skipped unless ENFORCE_JWT_SIGNATURE=true)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("ENFORCE_JWT_SIGNATURE"),
    reason="Only runs with ENFORCE_JWT_SIGNATURE=true",
)
def test_7_unsigned_jwt_rejected(monkeypatch):
    """An unsigned (alg=none) JWT must be rejected when signature enforcement is on."""
    from hi_agent.server.app import AgentServer

    monkeypatch.setenv("HI_AGENT_API_KEY", "test-key-for-isolation-test-7")
    server = AgentServer(rate_limit_rps=10000)
    unsigned = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ1MSJ9."
    client = TestClient(
        server.app,
        headers={"Authorization": f"Bearer {unsigned}"},
        raise_server_exceptions=False,
    )
    resp = client.get("/runs")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 8: POST /runs without X-Session-Id creates session and returns it
# ---------------------------------------------------------------------------


def test_8_post_runs_creates_session_when_absent(shared_manager, ctx_a, session_store):
    """POST /runs without X-Session-Id header must auto-create a session.

    The session ID must be returned in the X-Session-Id response header.
    """
    app = _build_isolation_app(shared_manager, ctx_a, session_store=session_store)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/runs", json={"goal": "fresh run"})
    assert resp.status_code == 201
    sid = resp.headers.get("x-session-id") or resp.headers.get("X-Session-Id")
    assert sid is not None and len(sid) > 0
    # Session must exist in the store
    assert session_store.get(sid) is not None


# ---------------------------------------------------------------------------
# Test 9: GET /health does not create any sessions
# ---------------------------------------------------------------------------


def test_9_health_does_not_create_session(shared_manager, ctx_a, session_store):
    """GET /health must not create any sessions in the session store."""
    app = _build_isolation_app(shared_manager, ctx_a, session_store=session_store)
    client = TestClient(app, raise_server_exceptions=False)
    before = session_count(session_store)
    client.get("/health")
    after = session_count(session_store)
    assert after == before


# ---------------------------------------------------------------------------
# Test 10: Session belonging to another user returns 403
# ---------------------------------------------------------------------------


def test_10_session_id_from_other_user_returns_403(shared_manager, ctx_a, ctx_b, session_store):
    """User B using User A's session ID must receive 403.

    Creates a session for user A, then user B attempts to POST /runs using
    that session ID, which must be rejected.
    """
    # Create session_a directly (simulating what SessionMiddleware would do for user A)
    session_a = session_store.create(
        tenant_id=ctx_a.tenant_id,
        user_id=ctx_a.user_id,
    )

    # Build app injecting ctx_b so the request runs as user B
    app = _build_isolation_app(shared_manager, ctx_b, session_store=session_store)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/runs",
        json={"goal": "inject"},
        headers={"X-Session-Id": session_a},
    )
    assert resp.status_code == 403
