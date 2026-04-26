"""Cross-tenant isolation integration tests for long-running op routes (W5-G).

Verifies that Tenant A cannot read or cancel Tenant B's long-running operations.

Layer 2 — Integration: real route handlers wired to a fake OpCoordinator.
No MagicMock on the subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server import routes_ops
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


class _FakeOpHandle:
    """Minimal stand-in for an OpHandle returned by coord.get()."""

    def __init__(self, op_id: str, tenant_id: str) -> None:
        self.op_id = op_id
        self.tenant_id = tenant_id
        self.backend = "test"
        self.status = "running"
        self.artifacts_uri = ""
        self.submitted_at = 0.0
        self.heartbeat_at = 0.0
        self.completed_at = 0.0
        self.error = ""


class _FakeOpCoordinator:
    """Minimal op coordinator backed by a dict."""

    def __init__(self) -> None:
        self._ops: dict[str, _FakeOpHandle] = {}

    def register(self, handle: _FakeOpHandle) -> None:
        self._ops[handle.op_id] = handle

    def get(self, op_id: str) -> _FakeOpHandle | None:
        return self._ops.get(op_id)

    def cancel(self, op_id: str) -> bool:
        if op_id in self._ops:
            self._ops[op_id].status = "cancelled"
            return True
        return False


class _FakeServer:
    """Minimal stand-in for AgentServer used by op route handlers."""

    def __init__(self, coord: _FakeOpCoordinator) -> None:
        self.op_coordinator = coord


def _build_app(coord: _FakeOpCoordinator, ctx: TenantContext) -> Starlette:
    """Build a minimal ASGI app with /long-ops routes and injected TenantContext."""
    app_routes = [
        Route("/long-ops/{op_id}", routes_ops.handle_get_long_op, methods=["GET"]),
        Route(
            "/long-ops/{op_id}/cancel",
            routes_ops.handle_cancel_long_op,
            methods=["POST"],
        ),
    ]
    app = Starlette(routes=app_routes)
    app.state.agent_server = _FakeServer(coord)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrossTenantOpIsolation:
    """GET /long-ops/{op_id} and POST /long-ops/{op_id}/cancel — cross-tenant denial."""

    @pytest.fixture()
    def coord(self):
        return _FakeOpCoordinator()

    @pytest.fixture()
    def op_a(self, coord) -> _FakeOpHandle:
        handle = _FakeOpHandle(op_id="op-A1", tenant_id="tenant-A")
        coord.register(handle)
        return handle

    def test_tenant_b_cannot_read_tenant_a_op(self, coord, op_a):
        """GET /long-ops/{op_id} from Tenant B on a Tenant A op → 404."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")
        app = _build_app(coord, ctx_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/long-ops/{op_a.op_id}")
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant op read, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_a_can_read_own_op(self, coord, op_a):
        """GET /long-ops/{op_id} from Tenant A on its own op → 200."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
        app = _build_app(coord, ctx_a)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/long-ops/{op_a.op_id}")
        assert resp.status_code == 200, (
            f"Expected 200 for same-tenant op read, got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("op_id") == op_a.op_id

    def test_tenant_b_cannot_cancel_tenant_a_op(self, coord, op_a):
        """POST /long-ops/{op_id}/cancel from Tenant B on Tenant A op → 404."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")
        app = _build_app(coord, ctx_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(f"/long-ops/{op_a.op_id}/cancel")
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant op cancel, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_a_can_cancel_own_op(self, coord, op_a):
        """POST /long-ops/{op_id}/cancel from Tenant A on its own op → 200."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
        app = _build_app(coord, ctx_a)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(f"/long-ops/{op_a.op_id}/cancel")
        assert resp.status_code == 200, (
            f"Expected 200 for same-tenant op cancel, got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("cancelled") is True

    def test_get_nonexistent_op_returns_404(self, coord):
        """GET /long-ops/{nonexistent_id} → 404 regardless of tenant."""
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
        app = _build_app(coord, ctx)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/long-ops/nonexistent-op-999")
        assert resp.status_code == 404

    def test_op_without_tenant_id_field_is_accessible(self, coord):
        """Op handles missing tenant_id field (legacy) are accessible to all tenants.

        Pre-tenant-spine handles have no tenant_id attribute. The handler
        uses getattr(handle, 'tenant_id', '') which gives '' → no filter applied.
        """
        legacy_handle = _FakeOpHandle(op_id="op-legacy", tenant_id="")
        coord.register(legacy_handle)

        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")
        app = _build_app(coord, ctx_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/long-ops/op-legacy")
        # Legacy ops (no tenant_id) are visible to all tenants (dev-compat)
        assert resp.status_code == 200
