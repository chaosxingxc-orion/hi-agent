"""Integration test: artifact routes work correctly with both backends (C1/C2 fix).

Parametrized over ArtifactRegistry (in-memory) and ArtifactLedger (durable file)
to verify that tenant scoping works on both backends without TypeError/500.

Covers:
- Same-tenant GET → 200 with artifact
- Cross-tenant GET → 404, NOT 500
- Same-tenant LIST → returns the artifact
- Cross-tenant LIST → empty list, NOT 500
- Cross-tenant by-project → empty or 404, NOT 500
"""
from __future__ import annotations

from pathlib import Path

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


class _FakeServer:
    def __init__(self, registry) -> None:
        self.artifact_registry = registry


def _build_app(ctx: TenantContext, registry):
    server = _FakeServer(registry)
    app = Starlette(routes=artifact_routes)
    app.state.agent_server = server
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.fixture(autouse=True)
def _dev_posture(monkeypatch):
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


@pytest.fixture(params=["in_memory", "durable"])
def store(request, tmp_path: Path):
    """Parametrized fixture returning (backend_label, store_instance)."""
    if request.param == "in_memory":
        from hi_agent.artifacts.registry import ArtifactRegistry
        return "in_memory", ArtifactRegistry()
    else:
        from hi_agent.artifacts.ledger import ArtifactLedger
        return "durable", ArtifactLedger(tmp_path / "test_ledger.jsonl")


@pytest.fixture()
def artifact_tenant_a():
    return Artifact(
        artifact_id="art-tenant-a-1",
        artifact_type="base",
        project_id="proj-A",
        tenant_id="tenant-A",
    )


def test_same_tenant_get_returns_200(store, artifact_tenant_a):
    """Same-tenant GET /artifacts/{id} returns 200."""
    label, backend = store
    backend.store(artifact_tenant_a)

    ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-A")
    app = _build_app(ctx_a, backend)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(f"/artifacts/{artifact_tenant_a.artifact_id}")
    assert resp.status_code == 200, (
        f"[{label}] Expected 200 for same-tenant GET, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["artifact_id"] == artifact_tenant_a.artifact_id


def test_cross_tenant_get_returns_404_not_500(store, artifact_tenant_a):
    """Cross-tenant GET /artifacts/{id} returns 404, NOT 500."""
    label, backend = store
    backend.store(artifact_tenant_a)

    ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-B")
    app = _build_app(ctx_b, backend)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(f"/artifacts/{artifact_tenant_a.artifact_id}")
    assert resp.status_code == 404, (
        f"[{label}] Expected 404 for cross-tenant GET, got {resp.status_code}: {resp.text}"
    )


def test_same_tenant_list_returns_artifact(store, artifact_tenant_a):
    """Same-tenant GET /artifacts returns the artifact."""
    label, backend = store
    backend.store(artifact_tenant_a)

    ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-A")
    app = _build_app(ctx_a, backend)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/artifacts")
    assert resp.status_code == 200, (
        f"[{label}] Expected 200 for same-tenant LIST, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert data["count"] >= 1
    ids = [a["artifact_id"] for a in data["artifacts"]]
    assert artifact_tenant_a.artifact_id in ids


def test_cross_tenant_list_returns_empty_not_500(store, artifact_tenant_a):
    """Cross-tenant GET /artifacts returns empty list, NOT 500."""
    label, backend = store
    backend.store(artifact_tenant_a)

    ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-B")
    app = _build_app(ctx_b, backend)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/artifacts")
    assert resp.status_code == 200, (
        f"[{label}] Expected 200 (empty list) for cross-tenant LIST, "
        f"got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert data["count"] == 0, f"[{label}] Expected 0 artifacts for cross-tenant, got {data}"


def test_cross_tenant_by_project_returns_404_not_500(store, artifact_tenant_a):
    """Cross-tenant GET /artifacts/by-project/{id} returns 404, NOT 500."""
    label, backend = store
    backend.store(artifact_tenant_a)

    ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-B")
    app = _build_app(ctx_b, backend)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(f"/artifacts/by-project/{artifact_tenant_a.project_id}")
    # Either 404 (all candidates belong to different tenant) or 200 with empty list
    # are acceptable — the key invariant is NOT 500.
    assert resp.status_code in (404, 200), (
        f"[{label}] Expected 404 or 200 for cross-tenant by-project, "
        f"got {resp.status_code}: {resp.text}"
    )
    if resp.status_code == 200:
        data = resp.json()
        assert data["count"] == 0, (
            f"[{label}] Expected empty artifacts for cross-tenant by-project, got {data}"
        )
