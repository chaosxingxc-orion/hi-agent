"""Integration test: posture-aware policy for legacy tenantless artifacts (D1/D2).

Verifies:
1. Under research posture: cross-tenant access to legacy (tenant_id="") artifacts is denied.
   - registry.get() → None (404 via HTTP)
   - denied counter incremented
2. Under dev posture: cross-tenant access to legacy artifacts is allowed.
   - registry.get() → artifact (200 via HTTP)
   - visible counter incremented
   - log contains 'legacy tenantless'
"""
from __future__ import annotations

import logging

import pytest
from hi_agent.artifacts.contracts import Artifact
from hi_agent.artifacts.metrics import (
    legacy_tenantless_denied_total,
    legacy_tenantless_visible_total,
)
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
def _reset_counters():
    """Reset metrics counters before each test."""
    legacy_tenantless_denied_total.reset()
    legacy_tenantless_visible_total.reset()
    yield


@pytest.fixture()
def legacy_artifact():
    """Artifact with tenant_id='' — represents pre-CO-5 legacy data."""
    return Artifact(
        artifact_id="legacy-001",
        artifact_type="base",
        project_id="proj-legacy",
        tenant_id="",  # legacy: no tenant assigned
    )


# ---------------------------------------------------------------------------
# research posture: deny
# ---------------------------------------------------------------------------


def test_research_posture_cross_tenant_get_denied(monkeypatch, legacy_artifact):
    """Under research posture, tenant-B cannot access legacy tenantless artifact."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry.__new__(ArtifactRegistry)
    reg._store = {}
    reg._store[legacy_artifact.artifact_id] = legacy_artifact

    ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-B")
    app = _build_app(ctx_b, reg)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(f"/artifacts/{legacy_artifact.artifact_id}")
    assert resp.status_code == 404, (
        f"Expected 404 (denied) under research posture, got {resp.status_code}: {resp.text}"
    )


def test_research_posture_denied_counter_incremented(monkeypatch, legacy_artifact):
    """Under research posture, denied counter is incremented on legacy artifact access."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry.__new__(ArtifactRegistry)
    reg._store = {}
    reg._store[legacy_artifact.artifact_id] = legacy_artifact

    before = legacy_tenantless_denied_total.total()
    result = reg.get(legacy_artifact.artifact_id, tenant_id="tenant-B")
    assert result is None
    assert legacy_tenantless_denied_total.total() > before, (
        "Expected denied counter to be incremented under research posture"
    )


def test_research_posture_denied_warning_logged(monkeypatch, legacy_artifact, caplog):
    """Under research posture, WARNING log is emitted for legacy artifact denial."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry.__new__(ArtifactRegistry)
    reg._store = {}
    reg._store[legacy_artifact.artifact_id] = legacy_artifact

    with caplog.at_level(logging.WARNING, logger="hi_agent.artifacts.registry"):
        reg.get(legacy_artifact.artifact_id, tenant_id="tenant-B")

    assert any("legacy tenantless" in r.message for r in caplog.records), (
        f"Expected WARNING with 'legacy tenantless' in log. Records: {caplog.records}"
    )


# ---------------------------------------------------------------------------
# dev posture: allow
# ---------------------------------------------------------------------------


def test_dev_posture_cross_tenant_get_allowed(monkeypatch, legacy_artifact):
    """Under dev posture, tenant-B can access legacy tenantless artifact."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry.__new__(ArtifactRegistry)
    reg._store = {}
    reg._store[legacy_artifact.artifact_id] = legacy_artifact

    ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-B")
    app = _build_app(ctx_b, reg)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(f"/artifacts/{legacy_artifact.artifact_id}")
    assert resp.status_code == 200, (
        f"Expected 200 (allowed) under dev posture, got {resp.status_code}: {resp.text}"
    )


def test_dev_posture_visible_counter_incremented(monkeypatch, legacy_artifact):
    """Under dev posture, visible counter is incremented on legacy artifact access."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry.__new__(ArtifactRegistry)
    reg._store = {}
    reg._store[legacy_artifact.artifact_id] = legacy_artifact

    before = legacy_tenantless_visible_total.total()
    result = reg.get(legacy_artifact.artifact_id, tenant_id="tenant-B")
    assert result is not None
    assert legacy_tenantless_visible_total.total() > before, (
        "Expected visible counter to be incremented under dev posture"
    )


def test_dev_posture_visible_debug_logged(monkeypatch, legacy_artifact, caplog):
    """Under dev posture, debug log is emitted for legacy artifact visibility."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from hi_agent.artifacts.registry import ArtifactRegistry

    reg = ArtifactRegistry.__new__(ArtifactRegistry)
    reg._store = {}
    reg._store[legacy_artifact.artifact_id] = legacy_artifact

    with caplog.at_level(logging.DEBUG, logger="hi_agent.artifacts.registry"):
        reg.get(legacy_artifact.artifact_id, tenant_id="tenant-B")

    assert any("legacy tenantless" in r.message for r in caplog.records), (
        f"Expected log with 'legacy tenantless' in dev posture. Records: {caplog.records}"
    )
