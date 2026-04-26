"""Integration test: POST /runs → RunManager → RunQueue → durable row has full spine.

Layer 2 — Integration: real RunManager + real RunQueue (SQLite).
Zero mocks on the subsystem under test.

Asserts that tenant_id, user_id, session_id, and project_id are all
non-empty and match the auth context after a POST /runs call.
"""
from __future__ import annotations

import sqlite3

import pytest
from hi_agent.server import routes_runs
from hi_agent.server.run_manager import RunManager
from hi_agent.server.run_queue import RunQueue
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware:
    """ASGI middleware that injects a fixed TenantContext for each request."""

    def __init__(self, app, ctx: TenantContext) -> None:
        self.app = app
        self._ctx = ctx

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            token = set_tenant_context(self._ctx)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_tenant_context(token)
        else:
            await self.app(scope, receive, send)


class _FakeServer:
    """Minimal AgentServer stand-in used by run route handlers."""

    def __init__(self, manager: RunManager) -> None:
        self.run_manager = manager
        self.run_context_manager = None
        self.executor_factory = None
        self.artifact_registry = None
        self._feedback_store = None


def _build_app(manager: RunManager, ctx: TenantContext) -> Starlette:
    routes = [
        Route("/runs", routes_runs.handle_create_run, methods=["POST"]),
        Route("/runs/{run_id}", routes_runs.handle_get_run, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(manager)
    # Wrap with context-injecting middleware
    return _InjectCtxMiddleware(app, ctx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunQueueSpineViaHttp:
    """POST /runs — verify all four spine fields land in the run_queue row."""

    @pytest.fixture()
    def db_path(self, tmp_path):
        return str(tmp_path / "run_queue.sqlite")

    @pytest.fixture()
    def ctx(self):
        return TenantContext(
            tenant_id="tenant-spine-test",
            user_id="user-spine-test",
            session_id="session-spine-test",
        )

    @pytest.fixture()
    def manager(self, db_path):
        rq = RunQueue(db_path=db_path)
        rm = RunManager(run_queue=rq)
        yield rm
        rm.shutdown()

    def test_enqueue_populates_all_spine_fields(self, manager, db_path, ctx):
        """POST /runs → run_queue row must have non-empty tenant_id, user_id,
        session_id, and project_id matching the authenticated TenantContext."""
        app = _build_app(manager, ctx)
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/runs",
                json={"goal": "spine test goal", "project_id": "proj-spine-test"},
            )
        assert resp.status_code in (200, 201, 202), f"create failed: {resp.text}"
        run_id = resp.json().get("run_id")
        assert run_id, "response must include run_id"

        # Directly query the SQLite run_queue to verify spine fields.
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT tenant_id, user_id, session_id, project_id "
            "FROM run_queue WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        conn.close()

        assert row is not None, f"run_id {run_id!r} not found in run_queue"
        tenant_id, user_id, session_id, project_id = row

        assert tenant_id == ctx.tenant_id, (
            f"tenant_id mismatch: got {tenant_id!r}, expected {ctx.tenant_id!r}"
        )
        assert user_id == ctx.user_id, (
            f"user_id mismatch: got {user_id!r}, expected {ctx.user_id!r}"
        )
        assert session_id == ctx.session_id, (
            f"session_id mismatch: got {session_id!r}, expected {ctx.session_id!r}"
        )
        assert project_id == "proj-spine-test", (
            f"project_id mismatch: got {project_id!r}, expected 'proj-spine-test'"
        )

    def test_spine_non_empty_even_without_project_id(self, manager, db_path, ctx):
        """When project_id is absent in dev posture, tenant/user/session must
        still be non-empty in the run_queue row."""
        app = _build_app(manager, ctx)
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post("/runs", json={"goal": "no project id test"})
        assert resp.status_code in (200, 201, 202), f"create failed: {resp.text}"
        run_id = resp.json().get("run_id")
        assert run_id

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT tenant_id, user_id, session_id FROM run_queue WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        tenant_id, user_id, session_id = row
        assert tenant_id, "tenant_id must not be empty"
        assert user_id, "user_id must not be empty"
        assert session_id, "session_id must not be empty"
