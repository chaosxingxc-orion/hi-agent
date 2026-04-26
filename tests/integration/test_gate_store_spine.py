"""Track Spine-1: gate store and gate context carry contract spine.

Verifies that SQLiteGateStore and InMemoryGateAPI propagate tenant/user/
session/project spine onto GateContext at create time and reload them on
read.  Also verifies cross-tenant denial at the HTTP gate decision route
(POST /runs/{run_id}/gate_decision) — the only HTTP surface that resolves
gate ownership today.

Layer 2 — Integration: real SQLite store, real RunManager.  No MagicMock
on the subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.management.gate_api import GateStatus, InMemoryGateAPI
from hi_agent.management.gate_context import build_gate_context
from hi_agent.management.gate_store import SQLiteGateStore
from hi_agent.server import routes_runs
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


def _make_context(gate_ref: str = "g1"):
    return build_gate_context(
        gate_ref=gate_ref,
        run_id="run-1",
        stage_id="stage-1",
        branch_id="branch-1",
        submitter="alice",
    )


def test_gate_store_spine_roundtrip(tmp_path):
    """create_gate with spine kwargs → get_gate returns context with spine."""
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    store.create_gate(
        context=_make_context("g1"),
        tenant_id="tenant-A",
        user_id="user-a",
        session_id="sess-a",
        project_id="proj-a",
    )
    record = store.get_gate("g1")
    assert record.context.tenant_id == "tenant-A"
    assert record.context.user_id == "user-a"
    assert record.context.session_id == "sess-a"
    assert record.context.project_id == "proj-a"
    store.close()


def test_gate_store_list_pending_returns_spine(tmp_path):
    """list_pending must populate spine fields on each returned record."""
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    store.create_gate(
        context=_make_context("g-a"),
        tenant_id="tenant-A",
        user_id="user-a",
        session_id="sess-a",
        project_id="proj-a",
    )
    store.create_gate(
        context=_make_context("g-b"),
        tenant_id="tenant-B",
        user_id="user-b",
        session_id="sess-b",
        project_id="proj-b",
    )
    pending = store.list_pending()
    by_ref = {r.context.gate_ref: r for r in pending}
    assert by_ref["g-a"].context.tenant_id == "tenant-A"
    assert by_ref["g-a"].context.project_id == "proj-a"
    assert by_ref["g-b"].context.tenant_id == "tenant-B"
    assert by_ref["g-b"].context.user_id == "user-b"
    assert by_ref["g-b"].context.session_id == "sess-b"
    assert all(r.status == GateStatus.PENDING for r in pending)
    store.close()


def test_in_memory_gate_api_spine_propagated():
    """InMemoryGateAPI.create_gate must copy spine kwargs onto context."""
    api = InMemoryGateAPI()
    record = api.create_gate(
        context=_make_context("gx"),
        tenant_id="tenant-A",
        user_id="user-a",
        session_id="sess-a",
        project_id="proj-a",
    )
    assert record.context.tenant_id == "tenant-A"
    assert record.context.user_id == "user-a"
    assert record.context.session_id == "sess-a"
    assert record.context.project_id == "proj-a"
    fetched = api.get_gate("gx")
    assert fetched.context.tenant_id == "tenant-A"


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


class _FakeServer:
    def __init__(self, manager: RunManager) -> None:
        self.run_manager = manager
        self.run_context_manager = None
        self.executor_factory = None
        self.artifact_registry = None
        self._feedback_store = None


def _build_runs_app(manager: RunManager, ctx: TenantContext) -> Starlette:
    routes = [
        Route("/runs", routes_runs.handle_create_run, methods=["POST"]),
        Route(
            "/runs/{run_id}/gate_decision",
            routes_runs.handle_gate_decision,
            methods=["POST"],
        ),
    ]
    app = Starlette(routes=routes)
    server = _FakeServer(manager)
    app.state.agent_server = server
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


CTX_A = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
CTX_B = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")


def test_gate_store_cross_tenant_denial():
    """Tenant B cannot resolve a gate decision on Tenant A's run (object-level 404)."""
    manager = RunManager()
    try:
        app_a = _build_runs_app(manager, CTX_A)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            r = ca.post("/runs", json={"goal": "tenant A gate task"})
            assert r.status_code in (200, 201, 202), f"create failed: {r.text}"
            run_id = r.json().get("run_id")
            assert run_id

        app_b = _build_runs_app(manager, CTX_B)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post(
                f"/runs/{run_id}/gate_decision",
                json={"decision": "approve", "approver_id": "user-b"},
            )
            assert resp.status_code == 404, (
                f"Expected 404 cross-tenant denial, got {resp.status_code}: {resp.text}"
            )
    finally:
        manager.shutdown()
