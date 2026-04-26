"""Cross-tenant isolation integration tests for artifact routes (W5-G).

Verifies that Tenant B cannot read Tenant A's artifacts via any artifact endpoint.

Layer 2 — Integration: real ArtifactRegistry + real route handlers.
No MagicMock on the subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.artifacts.contracts import Artifact
from hi_agent.artifacts.registry import ArtifactRegistry
from hi_agent.server.routes_artifacts import artifact_routes
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
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
    def __init__(self, registry: ArtifactRegistry) -> None:
        self.artifact_registry = registry


def _build_app(registry: ArtifactRegistry, ctx: TenantContext) -> Starlette:
    app = Starlette(routes=artifact_routes)
    app.state.agent_server = _FakeServer(registry)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _make_artifact(aid: str, tenant_id: str, project_id: str = "proj-A") -> Artifact:
    return Artifact(
        artifact_id=aid,
        artifact_type="text",
        content="secret data",
        producer_action_id="act1",
        tenant_id=tenant_id,
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry():
    reg = ArtifactRegistry()
    reg.store(_make_artifact("art-A1", "tenant-A", project_id="proj-A"))
    reg.store(_make_artifact("art-A2", "tenant-A", project_id="proj-A"))
    reg.store(_make_artifact("art-B1", "tenant-B", project_id="proj-B"))
    return reg


class TestListArtifactsCrossTenant:
    """GET /artifacts — tenant-scoped listing."""

    def test_tenant_b_cannot_see_tenant_a_artifacts(self, registry):
        """GET /artifacts for Tenant B must not return Tenant A's artifacts."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b")
        app = _build_app(registry, ctx_b)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/artifacts")
        assert resp.status_code == 200
        ids = {a["artifact_id"] for a in resp.json().get("artifacts", [])}
        assert "art-A1" not in ids
        assert "art-A2" not in ids

    def test_tenant_a_can_list_own_artifacts(self, registry):
        """GET /artifacts for Tenant A returns its own artifacts."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a")
        app = _build_app(registry, ctx_a)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/artifacts")
        assert resp.status_code == 200
        ids = {a["artifact_id"] for a in resp.json().get("artifacts", [])}
        assert "art-A1" in ids
        assert "art-A2" in ids
        assert "art-B1" not in ids


class TestGetArtifactCrossTenant:
    """GET /artifacts/{artifact_id} — cross-tenant access returns 404."""

    def test_tenant_b_cannot_get_tenant_a_artifact(self, registry):
        """GET /artifacts/art-A1 from Tenant B → 404."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b")
        app = _build_app(registry, ctx_b)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/artifacts/art-A1")
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant artifact get, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_a_can_get_own_artifact(self, registry):
        """GET /artifacts/art-A1 from Tenant A → 200."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a")
        app = _build_app(registry, ctx_a)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/artifacts/art-A1")
        assert resp.status_code == 200, (
            f"Expected 200 for same-tenant artifact get, got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("artifact_id") == "art-A1"


class TestGetArtifactProvenanceCrossTenant:
    """GET /artifacts/{artifact_id}/provenance — cross-tenant access returns 404."""

    def test_tenant_b_cannot_get_tenant_a_provenance(self, registry):
        """GET /artifacts/art-A1/provenance from Tenant B → 404."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b")
        app = _build_app(registry, ctx_b)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/artifacts/art-A1/provenance")
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant provenance, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_a_can_get_own_provenance(self, registry):
        """GET /artifacts/art-A1/provenance from Tenant A → 200."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a")
        app = _build_app(registry, ctx_a)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/artifacts/art-A1/provenance")
        assert resp.status_code == 200, (
            f"Expected 200 for same-tenant provenance, got {resp.status_code}: {resp.text}"
        )


class TestByProjectCrossTenant:
    """GET /artifacts/by-project/{project_id} — cross-tenant returns 404."""

    def test_tenant_b_cannot_get_tenant_a_project_artifacts(self, registry):
        """GET /artifacts/by-project/proj-A from Tenant B → 404."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b")
        app = _build_app(registry, ctx_b)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/artifacts/by-project/proj-A")
        assert resp.status_code == 404, (
            f"Expected 404 for cross-tenant by-project, got {resp.status_code}: {resp.text}"
        )

    def test_tenant_a_can_get_own_project_artifacts(self, registry):
        """GET /artifacts/by-project/proj-A from Tenant A → 200."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a")
        app = _build_app(registry, ctx_a)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/artifacts/by-project/proj-A")
        assert resp.status_code == 200, (
            f"Expected 200 for same-tenant by-project, got {resp.status_code}: {resp.text}"
        )
