"""Tenant isolation tests for /ops/dlq route (T-1' fix).

Endpoints audited:
    GET /ops/dlq

Audit finding (W31, T-1'): /ops/dlq accepted tenant_id from query_params with no
auth check, returning ALL tenants' DLQ rows when tenant_id was omitted.

Fix verified by these tests:
- Under research/prod posture, request without TenantContext → 401.
- Under research/prod posture, requests are scoped to ctx.tenant_id (NOT
  query-param-driven). Caller cannot read another tenant's DLQ rows.
- Under dev posture, missing context falls back to ``__anonymous__`` and
  emits a WARNING log (back-compat for unauthenticated dev fixtures).

Layer 2 — Integration: real route handler against a fake RunQueue.
"""
from __future__ import annotations

import pytest
from hi_agent.server import routes_ops_dlq
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
# Helpers
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext per request."""

    def __init__(self, app, ctx: TenantContext | None) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request: Request, call_next):
        if self._ctx is None:
            return await call_next(request)
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _FakeRunQueue:
    """Minimal stand-in for RunQueue.list_dlq()."""

    def __init__(self, rows_by_tenant: dict[str, list[dict]]) -> None:
        self._rows_by_tenant = rows_by_tenant

    def list_dlq(self, tenant_id: str | None = None) -> list[dict]:
        if tenant_id is None:
            # legacy behaviour — flat across tenants
            flat: list[dict] = []
            for rows in self._rows_by_tenant.values():
                flat.extend(rows)
            return flat
        return list(self._rows_by_tenant.get(tenant_id, []))


class _FakeServer:
    def __init__(self, q: _FakeRunQueue) -> None:
        self._run_queue = q


def _build_app(q: _FakeRunQueue, ctx: TenantContext | None) -> Starlette:
    app_routes = [
        Route("/ops/dlq", routes_ops_dlq.handle_list_dlq, methods=["GET"]),
    ]
    app = Starlette(routes=app_routes)
    app.state.agent_server = _FakeServer(q)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.fixture()
def queue_with_two_tenants():
    return _FakeRunQueue(
        {
            "tenant-A": [
                {"run_id": "run-A1", "tenant_id": "tenant-A", "reason": "x"},
                {"run_id": "run-A2", "tenant_id": "tenant-A", "reason": "y"},
            ],
            "tenant-B": [
                {"run_id": "run-B1", "tenant_id": "tenant-B", "reason": "z"},
            ],
        }
    )


# ---------------------------------------------------------------------------
# research/prod posture: fail-closed
# ---------------------------------------------------------------------------


class TestStrictPostureDlqTenantIsolation:
    """Under research/prod posture, /ops/dlq must require + scope by TenantContext."""

    def test_research_posture_rejects_unauthenticated(
        self, monkeypatch, queue_with_two_tenants
    ):
        """Missing TenantContext under research → 401."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        app = _build_app(queue_with_two_tenants, ctx=None)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ops/dlq")
        assert resp.status_code == 401, (
            f"Expected 401 under research without TenantContext, "
            f"got {resp.status_code}: {resp.text}"
        )

    def test_prod_posture_rejects_unauthenticated(
        self, monkeypatch, queue_with_two_tenants
    ):
        """Missing TenantContext under prod → 401."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        app = _build_app(queue_with_two_tenants, ctx=None)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ops/dlq")
        assert resp.status_code == 401

    def test_research_tenant_a_only_sees_own_rows(
        self, monkeypatch, queue_with_two_tenants
    ):
        """Tenant A authenticated → only tenant-A DLQ rows returned."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="s")
        app = _build_app(queue_with_two_tenants, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ops/dlq")
        assert resp.status_code == 200
        body = resp.json()
        rows = body["dead_lettered_runs"]
        assert all(r["tenant_id"] == "tenant-A" for r in rows), (
            f"tenant-A request leaked rows: {rows}"
        )
        assert len(rows) == 2

    def test_research_tenant_b_only_sees_own_rows(
        self, monkeypatch, queue_with_two_tenants
    ):
        """Tenant B authenticated → only tenant-B DLQ rows returned."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="s")
        app = _build_app(queue_with_two_tenants, ctx=ctx_b)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ops/dlq")
        assert resp.status_code == 200
        body = resp.json()
        rows = body["dead_lettered_runs"]
        assert all(r["tenant_id"] == "tenant-B" for r in rows), (
            f"tenant-B request leaked rows: {rows}"
        )
        assert len(rows) == 1

    def test_research_query_param_tenant_id_cannot_override_context(
        self, monkeypatch, queue_with_two_tenants
    ):
        """Caller cannot supply ?tenant_id=other under strict — context wins."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="s")
        app = _build_app(queue_with_two_tenants, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ops/dlq?tenant_id=tenant-B")
        assert resp.status_code == 200
        rows = resp.json()["dead_lettered_runs"]
        # Even though caller asked for tenant-B, only tenant-A rows are returned.
        assert all(r["tenant_id"] == "tenant-A" for r in rows)


# ---------------------------------------------------------------------------
# dev posture: permissive — anonymous fallback
# ---------------------------------------------------------------------------


class TestDevPostureDlqFallback:
    """Under dev posture, missing context emits a warning and proceeds."""

    def test_dev_posture_without_context_uses_anonymous(
        self, monkeypatch, caplog, queue_with_two_tenants
    ):
        """Dev + no context → returns anonymous-scoped rows (empty for our fixture)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        app = _build_app(queue_with_two_tenants, ctx=None)
        with caplog.at_level("WARNING"):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/ops/dlq")
        assert resp.status_code == 200
        # Anonymous tenant has no DLQ rows in our fixture, so list is empty.
        assert resp.json()["dead_lettered_runs"] == []
        # WARNING about missing tenant context emitted.
        warnings = [
            rec for rec in caplog.records if rec.levelname == "WARNING"
        ]
        assert any("tenant" in r.message.lower() for r in warnings), (
            f"Expected WARNING log mentioning tenant; got: {[r.message for r in warnings]}"
        )

    def test_dev_posture_with_context_scoped_to_tenant(
        self, monkeypatch, queue_with_two_tenants
    ):
        """Dev + valid context → scoped to that tenant (no leak)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="s")
        app = _build_app(queue_with_two_tenants, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/ops/dlq")
        assert resp.status_code == 200
        rows = resp.json()["dead_lettered_runs"]
        assert all(r["tenant_id"] == "tenant-A" for r in rows)
