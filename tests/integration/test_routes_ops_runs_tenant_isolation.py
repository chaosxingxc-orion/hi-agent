"""Tenant isolation regression for /ops/runs/{run_id}/full and /diagnose (W32 B-T1).

Audit finding (W32, B-T1): both handlers called ``require_tenant_context()``
but discarded the return value, then read ``workspace`` from query_params and
used that string as the tenant filter. An authenticated tenant could pass
``?workspace=tenant-b`` to read another tenant's data.

Fix verified:
    * Authenticated Tenant A → Tenant A's data, regardless of ``?workspace=``
      under research/prod posture.
    * ``?workspace=other-tenant`` under research/prod → 403 (cross-tenant
      scope escape rejected).
    * ``?workspace=`` matching ``ctx.tenant_id`` → 200, scoped to the
      authenticated tenant.
    * No ``TenantContext`` → 401.
    * Under dev posture, mismatching ``?workspace=`` is logged at WARNING
      and the authenticated tenant id wins (no scope escape, no 403 churn
      for legacy callers).

Layer 2 — Integration: real route handlers wired to a fake RunStore + EventStore.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_ops_runs import (
    handle_ops_run_diagnose,
    handle_ops_run_full,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Inject a fixed TenantContext (or None) per request."""

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


class _FakeRun:
    """Minimal stand-in for a RunRecord."""

    def __init__(self, run_id: str, tenant_id: str) -> None:
        self.run_id = run_id
        self.tenant_id = tenant_id
        self.status = "running"
        self.created_at = "2026-05-03T00:00:00Z"
        self.finished_at = None
        self.error_summary = None


class _FakeRunStore:
    """RunStore that enforces tenant scope via get_for_tenant."""

    def __init__(self, runs_by_tenant: dict[str, list[_FakeRun]]) -> None:
        self._by_tenant = runs_by_tenant

    def get_for_tenant(self, run_id: str, tenant_id: str) -> _FakeRun | None:
        for run in self._by_tenant.get(tenant_id, []):
            if run.run_id == run_id:
                return run
        return None


class _FakeEventStore:
    """Tenant-scoped event lookup used by the handlers."""

    def __init__(self, events_by_run: dict[tuple[str, str], list[dict]]) -> None:
        self._by_run = events_by_run

    def get_events(
        self,
        run_id: str,
        *,
        tenant_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        return list(self._by_run.get((run_id, tenant_id), []))[offset : offset + limit]


class _FakeServer:
    def __init__(self, run_store: _FakeRunStore, event_store: _FakeEventStore) -> None:
        self._run_store = run_store
        self._event_store = event_store


def _build_app(server: _FakeServer, ctx: TenantContext | None) -> Starlette:
    routes = [
        Route("/ops/runs/{run_id}/full", handle_ops_run_full, methods=["GET"]),
        Route(
            "/ops/runs/{run_id}/diagnose", handle_ops_run_diagnose, methods=["GET"]
        ),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = server
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.fixture()
def store_with_two_tenants():
    runs = {
        "tenant-a": [_FakeRun("run-A1", "tenant-a")],
        "tenant-b": [_FakeRun("run-B1", "tenant-b")],
    }
    events = {
        ("run-A1", "tenant-a"): [{"type": "stage_started", "stage_id": "gather"}],
        ("run-B1", "tenant-b"): [{"type": "stage_started", "stage_id": "gather"}],
    }
    return _FakeServer(_FakeRunStore(runs), _FakeEventStore(events))


# ---------------------------------------------------------------------------
# research/prod posture: cross-tenant query param rejected
# ---------------------------------------------------------------------------


class TestStrictPostureWorkspaceParamIsolation:
    """Under research/prod, ``?workspace=other`` must NOT bypass tenant scope."""

    @pytest.mark.parametrize("path", ["full", "diagnose"])
    def test_research_rejects_cross_tenant_workspace_param(
        self, monkeypatch, store_with_two_tenants, path
    ):
        """Tenant A asking for tenant-b's workspace → 403, not 200, not leaked."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx_a = TenantContext(tenant_id="tenant-a", user_id="u-a", session_id="s")
        app = _build_app(store_with_two_tenants, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/ops/runs/run-B1/{path}?workspace=tenant-b")
        assert resp.status_code == 403, (
            f"Expected 403 cross-tenant workspace rejection, got "
            f"{resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["error"] == "tenant_scope_violation"

    @pytest.mark.parametrize("path", ["full", "diagnose"])
    def test_prod_rejects_cross_tenant_workspace_param(
        self, monkeypatch, store_with_two_tenants, path
    ):
        """Same rule under prod posture."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        ctx_a = TenantContext(tenant_id="tenant-a", user_id="u-a", session_id="s")
        app = _build_app(store_with_two_tenants, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/ops/runs/run-B1/{path}?workspace=tenant-b")
        assert resp.status_code == 403

    @pytest.mark.parametrize("path", ["full", "diagnose"])
    def test_research_matching_workspace_is_accepted(
        self, monkeypatch, store_with_two_tenants, path
    ):
        """``?workspace=`` equal to ctx.tenant_id is allowed."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx_a = TenantContext(tenant_id="tenant-a", user_id="u-a", session_id="s")
        app = _build_app(store_with_two_tenants, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/ops/runs/run-A1/{path}?workspace=tenant-a")
        assert resp.status_code == 200
        body = resp.json()
        assert body["workspace"] == "tenant-a"

    @pytest.mark.parametrize("path", ["full", "diagnose"])
    def test_research_no_workspace_param_uses_authenticated_tenant(
        self, monkeypatch, store_with_two_tenants, path
    ):
        """Omitting ``workspace`` is not a 400 anymore — the auth ctx is the scope."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        ctx_a = TenantContext(tenant_id="tenant-a", user_id="u-a", session_id="s")
        app = _build_app(store_with_two_tenants, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/ops/runs/run-A1/{path}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["workspace"] == "tenant-a"

    @pytest.mark.parametrize("path", ["full", "diagnose"])
    def test_research_unauthenticated_returns_401(
        self, monkeypatch, store_with_two_tenants, path
    ):
        """No TenantContext at all → 401, regardless of ``workspace`` param."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        app = _build_app(store_with_two_tenants, ctx=None)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/ops/runs/run-A1/{path}?workspace=tenant-a")
        assert resp.status_code == 401
        assert resp.json()["error"] == "authentication_required"


# ---------------------------------------------------------------------------
# dev posture: mismatching workspace param is a WARNING, not a 403
# ---------------------------------------------------------------------------


class TestDevPostureWorkspaceParamFallback:
    """Under dev posture, mismatching workspace logs WARNING and uses ctx tenant."""

    @pytest.mark.parametrize("path", ["full", "diagnose"])
    def test_dev_mismatching_workspace_uses_authenticated_tenant(
        self, monkeypatch, caplog, store_with_two_tenants, path
    ):
        """Tenant A asking for tenant-b's workspace under dev → 404 (not 403, not leaked).

        Under dev posture we do NOT raise 403, but the data filter is still
        ``ctx.tenant_id`` — so a request for tenant B's run lands on tenant
        A's RunStore lookup and returns 404, with a WARNING in the log.
        """
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        ctx_a = TenantContext(tenant_id="tenant-a", user_id="u-a", session_id="s")
        app = _build_app(store_with_two_tenants, ctx=ctx_a)
        with caplog.at_level("WARNING"), TestClient(
            app, raise_server_exceptions=False
        ) as client:
            resp = client.get(f"/ops/runs/run-B1/{path}?workspace=tenant-b")
        # ctx.tenant_id wins — run-B1 is not in tenant-a's scope
        assert resp.status_code == 404, resp.text
        # WARNING about the mismatching workspace param
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "workspace" in r.message.lower() and "tenant" in r.message.lower()
            for r in warnings
        ), f"Expected workspace-mismatch WARNING; got: {[r.message for r in warnings]}"
