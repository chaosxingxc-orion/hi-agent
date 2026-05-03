"""Tenant isolation tests for /knowledge routes (T-2'/T-3' fix).

Endpoints audited:
    GET  /knowledge/query        (handle_knowledge_query)
    GET  /knowledge/status       (handle_knowledge_status)
    POST /knowledge/lint         (handle_knowledge_lint)

Audit findings (W31, T-2'/T-3' BLOCKER):
- handle_knowledge_query extracted ctx.tenant_id for the audit log only;
  km.query() / km.query_for_context() never received it.
- handle_knowledge_status / handle_knowledge_lint aggregated stats and lint
  issues across all tenants.

Fix verified by these tests:
- /knowledge/query under strict posture without TenantContext → 401.
- /knowledge/query: km.query() and km.query_for_context() must be called with
  the caller's tenant_id (verified via fake-manager kwarg capture).
- /knowledge/status under strict without context → 401; with context, get_stats
  is called with tenant_id.
- /knowledge/lint under strict without context → 401; with context, lint is
  called with tenant_id.

Layer 2 — Integration: real route handlers with a fake KnowledgeManager that
records the kwargs each call received.
"""

from __future__ import annotations

import pytest
from hi_agent.server.routes_knowledge import (
    handle_knowledge_lint,
    handle_knowledge_query,
    handle_knowledge_status,
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
    """Injects a fixed TenantContext per request, or none for the unauth case."""

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


class _FakeKnowledgeResult:
    total_results = 0


class _RecordingKnowledgeManager:
    """Captures every method call with kwargs so tests can assert tenant_id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def query(self, q, *, limit=10, tenant_id=None, **_):
        self.calls.append(("query", {"q": q, "limit": limit, "tenant_id": tenant_id}))
        return _FakeKnowledgeResult()

    def query_for_context(self, q, *, budget_tokens=1500, tenant_id=None, **_):
        self.calls.append(
            (
                "query_for_context",
                {"q": q, "budget_tokens": budget_tokens, "tenant_id": tenant_id},
            )
        )
        return ""

    def get_stats(self, *, tenant_id=None, **_):
        self.calls.append(("get_stats", {"tenant_id": tenant_id}))
        return {"pages": 0, "nodes": 0}

    def lint(self, *, tenant_id=None, **_):
        self.calls.append(("lint", {"tenant_id": tenant_id}))
        return []


class _FakeServer:
    def __init__(self, km) -> None:
        self.knowledge_manager = km
        self.retrieval_engine = None


def _build_app(km, ctx: TenantContext | None) -> Starlette:
    routes = [
        Route("/knowledge/query", handle_knowledge_query, methods=["GET"]),
        Route("/knowledge/status", handle_knowledge_status, methods=["GET"]),
        Route("/knowledge/lint", handle_knowledge_lint, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(km)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


# ---------------------------------------------------------------------------
# T-2': /knowledge/query — manager call must carry tenant_id
# ---------------------------------------------------------------------------


class TestKnowledgeQueryTenantFilter:
    """Manager.query / query_for_context must receive caller tenant_id."""

    def test_research_without_context_returns_401(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = _RecordingKnowledgeManager()
        app = _build_app(km, ctx=None)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/query?q=hello")
        assert resp.status_code == 401, (
            f"Expected 401 under research without context; got {resp.status_code}: {resp.text}"
        )
        # Manager must NOT be called when auth fails.
        assert km.calls == []

    def test_prod_without_context_returns_401(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        km = _RecordingKnowledgeManager()
        app = _build_app(km, ctx=None)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/query?q=hello")
        assert resp.status_code == 401
        assert km.calls == []

    def test_tenant_a_query_passes_tenant_a_to_manager(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = _RecordingKnowledgeManager()
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="s")
        app = _build_app(km, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/query?q=ai")
        assert resp.status_code == 200
        # Both methods must have been called with tenant_id=tenant-A.
        method_to_kwargs = dict(km.calls)
        assert "query" in method_to_kwargs
        assert method_to_kwargs["query"]["tenant_id"] == "tenant-A"
        assert "query_for_context" in method_to_kwargs
        assert method_to_kwargs["query_for_context"]["tenant_id"] == "tenant-A"

    def test_tenant_b_query_passes_tenant_b_to_manager(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = _RecordingKnowledgeManager()
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="s")
        app = _build_app(km, ctx=ctx_b)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/query?q=ml")
        assert resp.status_code == 200
        method_to_kwargs = dict(km.calls)
        assert method_to_kwargs["query"]["tenant_id"] == "tenant-B"
        assert method_to_kwargs["query_for_context"]["tenant_id"] == "tenant-B"


# ---------------------------------------------------------------------------
# T-3': /knowledge/status — manager.get_stats must carry tenant_id
# ---------------------------------------------------------------------------


class TestKnowledgeStatusTenantFilter:
    def test_research_without_context_returns_401(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = _RecordingKnowledgeManager()
        app = _build_app(km, ctx=None)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/status")
        assert resp.status_code == 401
        assert km.calls == []

    def test_tenant_a_status_passes_tenant_a(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = _RecordingKnowledgeManager()
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="s")
        app = _build_app(km, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/status")
        assert resp.status_code == 200
        method_to_kwargs = dict(km.calls)
        assert method_to_kwargs["get_stats"]["tenant_id"] == "tenant-A"

    def test_tenant_b_status_passes_tenant_b(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = _RecordingKnowledgeManager()
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="s")
        app = _build_app(km, ctx=ctx_b)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/status")
        assert resp.status_code == 200
        method_to_kwargs = dict(km.calls)
        assert method_to_kwargs["get_stats"]["tenant_id"] == "tenant-B"


# ---------------------------------------------------------------------------
# T-3': /knowledge/lint — manager.lint must carry tenant_id
# ---------------------------------------------------------------------------


class TestKnowledgeLintTenantFilter:
    def test_research_without_context_returns_401(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = _RecordingKnowledgeManager()
        app = _build_app(km, ctx=None)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/knowledge/lint")
        assert resp.status_code == 401
        assert km.calls == []

    def test_tenant_a_lint_passes_tenant_a(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = _RecordingKnowledgeManager()
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="s")
        app = _build_app(km, ctx=ctx_a)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/knowledge/lint")
        assert resp.status_code == 200
        method_to_kwargs = dict(km.calls)
        assert method_to_kwargs["lint"]["tenant_id"] == "tenant-A"


# ---------------------------------------------------------------------------
# KnowledgeManager unit-level checks: signature accepts tenant_id and raises
# under strict posture if missing.
# ---------------------------------------------------------------------------


class TestKnowledgeManagerSignature:
    def _make_manager(self):
        from hi_agent.knowledge.graph_renderer import GraphRenderer
        from hi_agent.knowledge.knowledge_manager import KnowledgeManager
        from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
        from hi_agent.knowledge.wiki import KnowledgeWiki
        from hi_agent.memory.long_term import LongTermMemoryGraph

        wiki = KnowledgeWiki(wiki_dir=".tmp/wiki")
        graph = LongTermMemoryGraph()
        renderer = GraphRenderer(graph)
        user_store = UserKnowledgeStore()
        return KnowledgeManager(wiki=wiki, user_store=user_store, graph=graph, renderer=renderer)

    def test_query_accepts_tenant_id_kwarg(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        km = self._make_manager()
        # Should not raise when tenant_id is provided.
        result = km.query("hello", limit=5, tenant_id="tenant-A")
        assert result is not None

    def test_query_strict_posture_requires_tenant_id(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = self._make_manager()
        from hi_agent.contracts.errors import TenantScopeError

        with pytest.raises(TenantScopeError):
            km.query("hello", limit=5, tenant_id=None)

    def test_get_stats_accepts_tenant_id_kwarg(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        km = self._make_manager()
        stats = km.get_stats(tenant_id="tenant-A")
        assert isinstance(stats, dict)

    def test_get_stats_strict_posture_requires_tenant_id(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = self._make_manager()
        from hi_agent.contracts.errors import TenantScopeError

        with pytest.raises(TenantScopeError):
            km.get_stats(tenant_id=None)

    def test_lint_accepts_tenant_id_kwarg(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        km = self._make_manager()
        issues = km.lint(tenant_id="tenant-A")
        assert isinstance(issues, list)

    def test_lint_strict_posture_requires_tenant_id(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = self._make_manager()
        from hi_agent.contracts.errors import TenantScopeError

        with pytest.raises(TenantScopeError):
            km.lint(tenant_id=None)

    def test_query_for_context_accepts_tenant_id_kwarg(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        km = self._make_manager()
        ctx = km.query_for_context("hello", budget_tokens=100, tenant_id="tenant-A")
        assert isinstance(ctx, str)

    def test_query_for_context_strict_posture_requires_tenant_id(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        km = self._make_manager()
        from hi_agent.contracts.errors import TenantScopeError

        with pytest.raises(TenantScopeError):
            km.query_for_context("hello", tenant_id=None)
