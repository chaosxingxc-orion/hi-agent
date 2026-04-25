"""Integration test: artifact cross-tenant scope enforcement (TE-3).

Verifies that GET /artifacts/by-project/{project_id} returns 404 when the
authenticated tenant does not own the requested project's artifacts.

Auth approach: _InjectCtxMiddleware injects TenantContext directly, matching
the pattern from test_workspace_isolation.py.

Note: since CO-5 (Artifact.tenant_id) has not landed yet, artifacts carry a
synthetic tenant_id attribute attached at test time to exercise the gate.
"""
from __future__ import annotations

import pytest
from hi_agent.artifacts.contracts import Artifact
from hi_agent.server.routes_artifacts import artifact_routes
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext, bypassing AuthMiddleware."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request, call_next):
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _TenantArtifact:
    """Wraps an Artifact with an explicit tenant_id (simulates CO-5 spine field)."""

    def __init__(self, artifact: Artifact, tenant_id: str) -> None:
        self._artifact = artifact
        self.tenant_id = tenant_id
        self.project_id = artifact.project_id

    def to_dict(self):
        d = self._artifact.to_dict()
        d["tenant_id"] = self.tenant_id
        return d


class _FakeRegistry:
    """Minimal artifact registry backed by a list."""

    def __init__(self, items) -> None:
        self._items = list(items)

    def find_by_project(self, project_id: str):
        return [i for i in self._items if i.project_id == project_id]

    def all(self):
        return list(self._items)


class _FakeServer:
    def __init__(self, registry) -> None:
        self.artifact_registry = registry


def _build_app(ctx: TenantContext, registry):
    server = _FakeServer(registry)

    async def _set_state(scope, receive, send):
        pass

    app = Starlette(routes=artifact_routes)
    app.state.agent_server = server
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.fixture()
def artifact_for_tenant_a():
    base = Artifact(artifact_id="art-A1", artifact_type="base", project_id="proj-A")
    return _TenantArtifact(base, tenant_id="tenant-A")


@pytest.fixture()
def registry(artifact_for_tenant_a):
    return _FakeRegistry([artifact_for_tenant_a])


def test_cross_tenant_access_returns_404(registry):
    """Tenant B accessing Tenant A's project returns 404, not 200."""
    ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-B")
    app = _build_app(ctx_b, registry)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/artifacts/by-project/proj-A")
    assert resp.status_code == 404, (
        f"Expected 404 for cross-tenant access, got {resp.status_code}: {resp.text}"
    )


def test_same_tenant_access_returns_200(registry):
    """Tenant A accessing their own project returns 200 with artifacts."""
    ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-A")
    app = _build_app(ctx_a, registry)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/artifacts/by-project/proj-A")
    assert resp.status_code == 200, (
        f"Expected 200 for same-tenant access, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert data["count"] == 1
    assert data["artifacts"][0]["project_id"] == "proj-A"
