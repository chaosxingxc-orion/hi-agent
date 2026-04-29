"""Tenant isolation: handle_knowledge_sync must not overwrite cross-tenant knowledge (AX-F F1).

Gap confirmed in W21 audit: knowledge_manager is a server-wide singleton.
POST /knowledge/sync triggers a global graph->wiki sync for ALL tenants' data.
Tenant B calling sync could overwrite or corrupt Tenant A's wiki pages because
the renderer operates on the shared global KG without tenant partitioning.
Tests are xfail until W22 implements per-tenant KG scoping.

Layer 2 — Integration: real route handlers, no MagicMock on subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_knowledge import (
    handle_knowledge_sync,
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


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext per request."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request: Request, call_next):
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _TrackingWiki:
    """Wiki stub that records which tenants' rebuild_index was called."""

    def __init__(self):
        self.rebuild_count = 0

    def rebuild_index(self):
        self.rebuild_count += 1


class _GlobalSyncManager:
    """Knowledge manager stub simulating the CURRENT global-sync behavior.

    to_wiki_pages operates on all pages without a tenant_id parameter.
    It records sync calls per (caller_tenant_id, pages_synced) to detect
    whether one tenant's sync inadvertently processes another tenant's data.
    """

    def __init__(self):
        self._pages: list[dict] = [
            {"tenant_id": "isolation-tenant-A", "title": "A-page"},
            {"tenant_id": "isolation-tenant-B", "title": "B-page"},
        ]
        self.sync_calls: list[dict] = []

    def to_wiki_pages(self, wiki) -> int:
        # Simulates current behavior: syncs ALL pages regardless of tenant
        pages_synced = len(self._pages)
        self.sync_calls.append({
            "pages_synced": pages_synced,
            "synced_all_tenants": True,
        })
        return pages_synced

    def to_wiki_pages_for_tenant(self, wiki, tenant_id: str) -> int:
        """What a correct implementation would look like."""
        pages_synced = sum(1 for p in self._pages if p.get("tenant_id") == tenant_id)
        self.sync_calls.append({
            "tenant_id": tenant_id,
            "pages_synced": pages_synced,
            "synced_all_tenants": False,
        })
        return pages_synced


class _GlobalKnowledgeManager:
    """Wraps the global sync manager, mirrors routes_knowledge.py interface."""

    def __init__(self, sync_mgr: _GlobalSyncManager, wiki: _TrackingWiki):
        self._sync_mgr = sync_mgr
        self._wiki = wiki

    @property
    def renderer(self):
        return self._sync_mgr

    @property
    def wiki(self):
        return self._wiki


class _FakeServer:
    def __init__(self, km) -> None:
        self.knowledge_manager = km
        self.retrieval_engine = None


def _build_app(km, ctx: TenantContext) -> Starlette:
    routes = [Route("/knowledge/sync", handle_knowledge_sync, methods=["POST"])]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(km)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.mark.xfail(
    reason=(
        "handle_knowledge_sync: knowledge_manager.renderer.to_wiki_pages() "
        "operates on the entire global graph without a tenant_id argument (W21 gap). "
        "Tenant B triggering sync re-renders ALL tenants' data, which could "
        "overwrite Tenant A's wiki pages. "
        "Fix in W22: pass tenant_id to to_wiki_pages() and limit sync scope."
    ),
    strict=False,
)
class TestKnowledgeSyncTenantIsolation:
    """POST /knowledge/sync must only sync the calling tenant's data (AX-F F1)."""

    def test_tenant_b_sync_does_not_process_tenant_a_pages(self):
        """Tenant B triggering sync must not render Tenant A's pages.

        Currently FAILS: to_wiki_pages() receives no tenant_id argument and
        processes all pages in the shared graph.
        """
        wiki = _TrackingWiki()
        sync_mgr = _GlobalSyncManager()
        km = _GlobalKnowledgeManager(sync_mgr, wiki)

        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")
        app_b = _build_app(km, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post("/knowledge/sync")
            assert resp.status_code == 200, f"Sync failed: {resp.text}"
            body = resp.json()
            pages_synced = body.get("pages_synced", 0)

        # In the current broken implementation, pages_synced == 2 (both tenants).
        # A correct tenant-scoped sync for B would return 1 (only B's page).
        assert pages_synced <= 1, (
            f"Tenant B sync processed {pages_synced} pages but should only process "
            f"Tenant B's own pages (expected <=1). "
            f"Sync scope leaked into other tenants' data."
        )

        # Verify that the sync call was recorded as tenant-scoped, not global.
        assert len(sync_mgr.sync_calls) == 1
        call = sync_mgr.sync_calls[0]
        assert not call.get("synced_all_tenants"), (
            f"Sync call processed all tenants' data: {call}. "
            "Expected tenant-scoped sync."
        )

    def test_sync_returns_only_calling_tenant_page_count(self):
        """pages_synced in response must equal the calling tenant's page count only.

        Currently FAILS: the global KM has no concept of per-tenant page counts.
        """
        wiki = _TrackingWiki()
        sync_mgr = _GlobalSyncManager()
        km = _GlobalKnowledgeManager(sync_mgr, wiki)

        ctx_a = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")
        app_a = _build_app(km, ctx_a)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            resp = ca.post("/knowledge/sync")
            assert resp.status_code == 200

        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")
        app_b = _build_app(km, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post("/knowledge/sync")
            assert resp.status_code == 200

        # Both sync calls should have processed exactly their own pages (1 each),
        # not all pages (2 each). In the broken implementation both return 2.
        for call in sync_mgr.sync_calls:
            assert call.get("pages_synced") == 1, (
                f"Sync call processed {call.get('pages_synced')} pages; "
                f"expected 1 (per-tenant). call={call}"
            )
