"""Tenant isolation: handle_knowledge_query must not leak cross-tenant data (AX-F F1).

Gap confirmed in W21 audit: knowledge_manager is a server-wide singleton.
GET /knowledge/query returns results from the global graph regardless of
which tenant is querying — Tenant B can retrieve Tenant A's ingested content.
Tests are xfail until W22 implements per-tenant KG filtering.

Layer 2 — Integration: real route handlers, no MagicMock on subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_knowledge import (
    handle_knowledge_ingest,
    handle_knowledge_query,
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


class _QueryResult:
    def __init__(self, total_results: int = 0):
        self.total_results = total_results


class _GlobalKnowledgeManager:
    """Minimal KM stub that simulates the CURRENT global-store behavior.

    All pages land in one shared dict, so queries return results regardless of
    which tenant ingested the content.
    """

    def __init__(self):
        self._pages: dict[str, dict] = {}
        self._context_map: dict[str, str] = {}  # query -> context

    def ingest_text(self, title: str, content: str, tags: list) -> str:
        page_id = f"page-{len(self._pages) + 1}"
        self._pages[page_id] = {"title": title, "content": content, "tags": tags}
        return page_id

    def query_for_context(self, q: str, budget_tokens: int = 1500) -> str:
        # Return content from ANY page matching the query (no tenant filter)
        for page in self._pages.values():
            if q.lower() in page.get("content", "").lower():
                return page["content"]
        return ""

    def query(self, q: str, limit: int = 10) -> _QueryResult:
        count = sum(
            1 for p in self._pages.values()
            if q.lower() in p.get("content", "").lower()
        )
        return _QueryResult(total_results=count)

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


def _build_ingest_app(km, ctx: TenantContext) -> Starlette:
    routes = [Route("/knowledge/ingest", handle_knowledge_ingest, methods=["POST"])]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(km)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _build_query_app(km, ctx: TenantContext) -> Starlette:
    routes = [Route("/knowledge/query", handle_knowledge_query, methods=["GET"])]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(km)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.mark.xfail(
    reason=(
        "handle_knowledge_query: knowledge_manager is a global singleton "
        "with no per-tenant data filtering (W21 gap). "
        "Tenant B's query returns content ingested by Tenant A because "
        "query_for_context and query() have no tenant_id filter parameter. "
        "Fix in W22: pass tenant_id to KnowledgeManager.query() and filter results."
    ),
    strict=False,
    expiry_wave="Wave 26",
)
class TestKnowledgeQueryTenantIsolation:
    """GET /knowledge/query must not return cross-tenant knowledge results (AX-F F1)."""

    def test_tenant_b_query_does_not_return_tenant_a_content(self):
        """Tenant B querying for a unique term must not find Tenant A's content.

        Currently FAILS: query() searches the global store without tenant filter.
        """
        km = _GlobalKnowledgeManager()
        unique_term = "xzq-secret-content-tenant-A-only"

        # Tenant A ingests content containing unique term
        ctx_a = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")
        app_a = _build_ingest_app(km, ctx_a)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            resp = ca.post(
                "/knowledge/ingest",
                json={
                    "title": "Private Knowledge",
                    "content": f"This contains the {unique_term}",
                },
            )
            assert resp.status_code == 201, f"Ingest failed: {resp.text}"

        # Tenant B queries for the unique term
        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")
        app_b = _build_query_app(km, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get(f"/knowledge/query?q={unique_term}")
            assert resp.status_code == 200, f"Query failed: {resp.text}"

            body = resp.json()
            context_text = body.get("context", "")
            total_results = body.get("total_results", 0)

            # In a correctly isolated system, Tenant B must get 0 results and
            # no context containing Tenant A's unique content.
            assert unique_term not in context_text, (
                f"Tenant B received Tenant A's content in query context. "
                f"context={context_text!r}"
            )
            assert total_results == 0, (
                f"Tenant B got {total_results} results for a term only in "
                f"Tenant A's knowledge base. Isolation gap confirmed."
            )

    def test_query_context_does_not_leak_cross_tenant_data(self):
        """The 'context' field in query response must be filtered to the calling tenant.

        Currently FAILS: query_for_context() operates on the shared global store.
        """
        km = _GlobalKnowledgeManager()
        secret_phrase = "tenant-A-confidential-phrase-99"

        ctx_a = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")
        app_a = _build_ingest_app(km, ctx_a)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            ca.post(
                "/knowledge/ingest",
                json={"title": "Confidential", "content": secret_phrase},
            )

        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")
        app_b = _build_query_app(km, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get(f"/knowledge/query?q={secret_phrase}")
            body = resp.json()
            context = body.get("context", "")
            assert secret_phrase not in context, (
                f"Tenant A's secret phrase leaked into Tenant B's query context: "
                f"context={context!r}"
            )
