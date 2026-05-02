"""Cross-tenant denial tests for knowledge routes.

Endpoints audited:
    POST /knowledge/ingest            (handle_knowledge_ingest)
    POST /knowledge/ingest-structured (handle_knowledge_ingest_structured)
    GET  /knowledge/query             (handle_knowledge_query)
    GET  /knowledge/status            (handle_knowledge_status)
    POST /knowledge/lint              (handle_knowledge_lint)
    POST /knowledge/sync              (handle_knowledge_sync)

Audit finding (W4-D): All six handlers already call require_tenant_context()
and return 401 for unauthenticated requests.  The knowledge_manager is a
server-wide singleton (not per-tenant), so architectural cross-tenant isolation
is a known platform gap (P-5); route-level enforcement is limited to auth.

Layer 2 — Integration: real route handlers, no MagicMock on subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_knowledge import (
    handle_knowledge_ingest,
    handle_knowledge_lint,
    handle_knowledge_query,
    handle_knowledge_status,
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


class _NoAuthMiddleware(BaseHTTPMiddleware):
    """Strips tenant context — simulates unauthenticated request."""

    async def dispatch(self, request: Request, call_next):
        return await call_next(request)


class _FakeKnowledgeResult:
    total_results = 0


class _FakeKnowledgeManager:
    """Minimal knowledge manager stub.

    W31, T-2'/T-3': accepts tenant_id kwarg on read methods (signature change).
    """

    def ingest_text(self, title, content, tags):
        return "page-001"

    def ingest_structured(self, facts):
        return len(facts)

    def query_for_context(self, q, budget_tokens=1500, *, tenant_id=None, **_):
        return ""

    def query(self, q, limit=10, *, tenant_id=None, **_):
        return _FakeKnowledgeResult()

    def get_stats(self, *, tenant_id=None, **_):
        return {"pages": 0, "nodes": 0}

    def lint(self, *, tenant_id=None, **_):
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
    def __init__(self) -> None:
        self.knowledge_manager = _FakeKnowledgeManager()
        self.retrieval_engine = _FakeRetrieval()


def _build_app(ctx: TenantContext) -> Starlette:
    routes = [
        Route("/knowledge/ingest", handle_knowledge_ingest, methods=["POST"]),
        Route("/knowledge/query", handle_knowledge_query, methods=["GET"]),
        Route("/knowledge/status", handle_knowledge_status, methods=["GET"]),
        Route("/knowledge/lint", handle_knowledge_lint, methods=["POST"]),
        Route("/knowledge/sync", handle_knowledge_sync, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer()
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _build_unauth_app() -> Starlette:
    routes = [
        Route("/knowledge/ingest", handle_knowledge_ingest, methods=["POST"]),
        Route("/knowledge/query", handle_knowledge_query, methods=["GET"]),
        Route("/knowledge/status", handle_knowledge_status, methods=["GET"]),
        Route("/knowledge/lint", handle_knowledge_lint, methods=["POST"]),
        Route("/knowledge/sync", handle_knowledge_sync, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer()
    app.add_middleware(_NoAuthMiddleware)
    return app


class TestKnowledgeRouteAuthEnforcement:
    """All knowledge routes must reject unauthenticated requests with 401."""

    def test_knowledge_ingest_requires_auth(self):
        """POST /knowledge/ingest without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/knowledge/ingest",
                json={"title": "test", "content": "test content"},
            )
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )

    def test_knowledge_query_requires_auth(self):
        """GET /knowledge/query without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/query?q=test")
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )

    def test_knowledge_status_requires_auth(self):
        """GET /knowledge/status without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/status")
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )

    def test_knowledge_lint_requires_auth(self):
        """POST /knowledge/lint without token must return 401."""
        app = _build_unauth_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/knowledge/lint")
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.text}"
            )


class TestKnowledgeRouteAuthenticatedAccess:
    """Authenticated tenants can use knowledge routes."""

    def test_authenticated_tenant_can_ingest(self):
        """POST /knowledge/ingest with valid auth returns 201."""
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-a")
        app = _build_app(ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/knowledge/ingest",
                json={"title": "Hello", "content": "World content"},
            )
            assert resp.status_code == 201, (
                f"Expected 201 for authenticated ingest, got {resp.status_code}: {resp.text}"
            )
            data = resp.json()
            assert "page_id" in data

    def test_authenticated_tenant_can_query(self):
        """GET /knowledge/query with valid auth returns 200."""
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-a")
        app = _build_app(ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/query?q=search+term")
            assert resp.status_code == 200, (
                f"Expected 200 for authenticated query, got {resp.status_code}: {resp.text}"
            )
            data = resp.json()
            assert "query" in data
