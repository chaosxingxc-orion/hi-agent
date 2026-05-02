"""Tenant isolation: handle_knowledge_ingest must reject cross-tenant access (AX-F F1).

Gap confirmed in W21 audit: knowledge_manager is a server-wide singleton.
Tenant B can ingest into the same global graph as Tenant A — no per-tenant
partition exists. Tests are xfail until W22 implements per-tenant KG scoping.

Layer 2 — Integration: real route handlers, no MagicMock on subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_knowledge import (
    handle_knowledge_ingest,
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


class _PartitionedPageStore:
    """Minimal knowledge manager that enforces per-tenant page partitioning.

    Used to verify what a correct implementation would look like.
    Each tenant's pages are stored in a separate namespace.
    """

    def __init__(self):
        # Map of tenant_id -> {page_id -> page_data}
        self._store: dict[str, dict] = {}

    def ingest_text(self, title: str, content: str, tags: list, tenant_id: str = "") -> str:
        page_id = f"{tenant_id}-page-{len(self._store.get(tenant_id, {})) + 1}"
        if tenant_id not in self._store:
            self._store[tenant_id] = {}
        self._store[tenant_id][page_id] = {"title": title, "content": content, "tags": tags}
        return page_id

    def get_page(self, page_id: str, tenant_id: str) -> dict | None:
        return self._store.get(tenant_id, {}).get(page_id)

    def get_stats(self):
        return {"pages": sum(len(v) for v in self._store.values()), "nodes": 0}

    def lint(self):
        return []

    @property
    def renderer(self):
        return self

    def to_wiki_pages(self, wiki):
        return 0

    @property
    def wiki(self):
        return self

    def rebuild_index(self):
        pass


class _GlobalPageStore:
    """Knowledge manager stub that simulates the CURRENT (broken) behavior:
    all tenants share one global store — no per-tenant partition.
    """

    def __init__(self):
        self._pages: dict[str, dict] = {}

    def ingest_text(self, title: str, content: str, tags: list) -> str:
        page_id = f"page-{len(self._pages) + 1}"
        self._pages[page_id] = {"title": title, "content": content, "tags": tags}
        return page_id

    def get_page(self, page_id: str) -> dict | None:
        return self._pages.get(page_id)

    def get_stats(self):
        return {"pages": len(self._pages), "nodes": 0}

    def lint(self):
        return []

    @property
    def renderer(self):
        return self

    def to_wiki_pages(self, wiki):
        return 0

    @property
    def wiki(self):
        return self

    def rebuild_index(self):
        pass


class _FakeRetrieval:
    def mark_index_dirty(self):
        pass


class _FakeServer:
    def __init__(self, km) -> None:
        self.knowledge_manager = km
        self.retrieval_engine = _FakeRetrieval()


def _build_app(km, ctx: TenantContext) -> Starlette:
    routes = [
        Route("/knowledge/ingest", handle_knowledge_ingest, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(km)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.mark.xfail(
    reason=(
        "handle_knowledge_ingest: knowledge_manager is a global singleton "
        "with no per-tenant partitioning (W21 gap). Tenant B can ingest into "
        "the same graph as Tenant A. Fix in W22: add tenant_id scoping to "
        "KnowledgeManager.ingest_text and enforce page ownership checks."
    ),
    strict=False,
    expiry_wave="Wave 30",
)
class TestKnowledgeIngestTenantIsolation:
    """POST /knowledge/ingest must isolate ingested pages by tenant (AX-F F1)."""

    def test_tenant_b_page_id_does_not_collide_with_tenant_a(self):
        """Tenant A and B ingesting the same title must produce tenant-scoped page IDs.

        Currently FAILS: both share the global store, so B's ingest can
        observe or overwrite A's namespace.
        """
        km = _GlobalPageStore()

        ctx_a = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")
        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")

        app_a = _build_app(km, ctx_a)
        with TestClient(app_a, raise_server_exceptions=False) as client_a:
            resp_a = client_a.post(
                "/knowledge/ingest",
                json={"title": "SharedTitle", "content": "Tenant A secret content"},
            )
            assert resp_a.status_code == 201, f"Tenant A ingest failed: {resp_a.text}"
            page_id_a = resp_a.json().get("page_id")
            assert page_id_a

        app_b = _build_app(km, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as client_b:
            resp_b = client_b.post(
                "/knowledge/ingest",
                json={"title": "SharedTitle", "content": "Tenant B content"},
            )
            assert resp_b.status_code == 201, f"Tenant B ingest failed: {resp_b.text}"
            page_id_b = resp_b.json().get("page_id")
            assert page_id_b

        # Page IDs must include tenant scope — same title must not produce the
        # same or conflicting global ID.
        assert page_id_a != page_id_b, (
            f"Tenant A and B got the same page_id={page_id_a!r}; "
            "ingest is not tenant-scoped"
        )
        # Tenant A's page ID must be scoped to A's namespace (contain tenant id or
        # be otherwise unguessable to B).
        assert "isolation-tenant-A" in page_id_a or page_id_a.startswith("isolation-tenant-A"), (
            f"page_id_a={page_id_a!r} does not encode tenant-A's namespace"
        )

    def test_tenant_b_cannot_reference_tenant_a_page_by_id(self):
        """A page ingested by Tenant A must not be accessible by Tenant B.

        Currently FAILS: the route does not check page ownership after ingest;
        a lookup by page_id would succeed cross-tenant on the global store.
        """
        km = _GlobalPageStore()

        ctx_a = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")

        app_a = _build_app(km, ctx_a)
        with TestClient(app_a, raise_server_exceptions=False) as client_a:
            resp_a = client_a.post(
                "/knowledge/ingest",
                json={"title": "PrivatePage", "content": "Tenant A private content"},
            )
            assert resp_a.status_code == 201
            page_id_a = resp_a.json().get("page_id")

        # The global store now contains Tenant A's page at page_id_a.
        # A correct implementation must NOT allow Tenant B to retrieve it.
        page = km.get_page(page_id_a)
        assert page is None, (
            f"Tenant B can access Tenant A's page via global store: "
            f"page_id={page_id_a!r} content={page}"
        )
