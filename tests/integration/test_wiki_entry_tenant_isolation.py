"""Integration tests: wiki/entry tenant scoping (W32 Track B Gap 6 / W33 T-9'/T-10').

The ``WikiPage`` and ``KnowledgeEntry`` dataclasses are value objects;
tenant scoping lives on the SqliteKnowledgeGraphBackend row, not on the
dataclass. After W32 Track B every public read/write path on
``KnowledgeManager`` accepts ``tenant_id`` and rejects an absent value
under research/prod posture.

These tests pin two invariants:

1. Strict posture rejects ingest/query/lint/status calls without
   ``tenant_id`` so cross-tenant write/read attribution can't silently leak.
2. The route handlers in ``hi_agent/server/routes_knowledge.py`` plumb
   ``ctx.tenant_id`` to ``KnowledgeManager`` on every call.

Layer 2 — Integration: real Starlette + real route handlers + a stub
KnowledgeManager that records the ``tenant_id`` it observes.
"""

from __future__ import annotations

import pytest
from hi_agent.server.routes_knowledge import (
    handle_knowledge_ingest,
    handle_knowledge_ingest_structured,
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


class _RecordingKnowledgeResult:
    total_results = 0


class _RecordingKM:
    """Knowledge manager stub that records every observed tenant_id."""

    def __init__(self) -> None:
        self.ingest_text_calls: list[tuple[str, str | None]] = []
        self.ingest_structured_calls: list[tuple[int, str | None]] = []
        self.query_calls: list[tuple[str, str | None]] = []
        self.lint_calls: list[str | None] = []
        self.stats_calls: list[str | None] = []

    # --- Write paths (W32 Track B Gap 6) ---

    def ingest_text(self, title, content, tags, *, tenant_id=None):
        self.ingest_text_calls.append((title, tenant_id))
        return f"page-{title}"

    def ingest_structured(self, facts, *, tenant_id=None):
        self.ingest_structured_calls.append((len(facts), tenant_id))
        return len(facts)

    # --- Read paths (W31 T-2'/T-3' regressions) ---

    def query(self, q, limit=10, *, tenant_id=None):
        self.query_calls.append((q, tenant_id))
        return _RecordingKnowledgeResult()

    def query_for_context(self, q, budget_tokens=1500, *, tenant_id=None):
        return ""

    def lint(self, *, tenant_id=None):
        self.lint_calls.append(tenant_id)
        return []

    def get_stats(self, *, tenant_id=None):
        self.stats_calls.append(tenant_id)
        return {"pages": 0, "nodes": 0}


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request: Request, call_next):
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _RecordingRetrieval:
    def mark_index_dirty(self):
        pass


class _RecordingServer:
    def __init__(self, km: _RecordingKM) -> None:
        self.knowledge_manager = km
        self.retrieval_engine = _RecordingRetrieval()


def _build_app(km: _RecordingKM, ctx: TenantContext) -> Starlette:
    app = Starlette(
        routes=[
            Route("/knowledge/ingest", handle_knowledge_ingest, methods=["POST"]),
            Route(
                "/knowledge/ingest-structured",
                handle_knowledge_ingest_structured,
                methods=["POST"],
            ),
            Route("/knowledge/query", handle_knowledge_query, methods=["GET"]),
            Route("/knowledge/status", handle_knowledge_status, methods=["GET"]),
            Route("/knowledge/lint", handle_knowledge_lint, methods=["POST"]),
        ]
    )
    app.state.agent_server = _RecordingServer(km)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


class TestRoutesPlumbTenantIdToKnowledgeManager:
    """Every route handler must pass ``ctx.tenant_id`` to KnowledgeManager."""

    def test_ingest_route_passes_tenant_id_on_write(self):
        km = _RecordingKM()
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-1")
        with TestClient(_build_app(km, ctx), raise_server_exceptions=False) as client:
            resp = client.post(
                "/knowledge/ingest",
                json={"title": "alpha", "content": "alpha-content"},
            )
            assert resp.status_code == 201, resp.text
        assert km.ingest_text_calls == [("alpha", "tenant-A")]

    def test_ingest_structured_route_passes_tenant_id_on_write(self):
        km = _RecordingKM()
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-1")
        with TestClient(_build_app(km, ctx), raise_server_exceptions=False) as client:
            resp = client.post(
                "/knowledge/ingest-structured",
                json={"facts": [{"content": "fact-1"}, {"content": "fact-2"}]},
            )
            assert resp.status_code == 201, resp.text
        assert km.ingest_structured_calls == [(2, "tenant-A")]

    def test_query_route_passes_tenant_id_on_read(self):
        km = _RecordingKM()
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-1")
        with TestClient(_build_app(km, ctx), raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/query?q=hello")
            assert resp.status_code == 200, resp.text
        assert km.query_calls == [("hello", "tenant-A")]

    def test_lint_route_passes_tenant_id(self):
        km = _RecordingKM()
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-1")
        with TestClient(_build_app(km, ctx), raise_server_exceptions=False) as client:
            resp = client.post("/knowledge/lint")
            assert resp.status_code == 200, resp.text
        assert km.lint_calls == ["tenant-A"]

    def test_status_route_passes_tenant_id(self):
        km = _RecordingKM()
        ctx = TenantContext(tenant_id="tenant-A", user_id="user-1")
        with TestClient(_build_app(km, ctx), raise_server_exceptions=False) as client:
            resp = client.get("/knowledge/status")
            assert resp.status_code == 200, resp.text
        assert km.stats_calls == ["tenant-A"]


class TestRoutesPropagateDistinctTenantIds:
    """Two tenants hitting the same route observe independent attribution."""

    def test_two_tenants_distinct_ingest_attribution(self):
        km = _RecordingKM()

        # Tenant A ingests through one app instance.
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-1")
        with TestClient(_build_app(km, ctx_a), raise_server_exceptions=False) as ca:
            r = ca.post("/knowledge/ingest", json={"title": "page-A", "content": "alpha"})
            assert r.status_code == 201

        # Tenant B ingests through a separate app instance, same KM.
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-2")
        with TestClient(_build_app(km, ctx_b), raise_server_exceptions=False) as cb:
            r = cb.post("/knowledge/ingest", json={"title": "page-B", "content": "bravo"})
            assert r.status_code == 201

        # The KM observed two distinct tenant_ids on its write path.
        assert ("page-A", "tenant-A") in km.ingest_text_calls
        assert ("page-B", "tenant-B") in km.ingest_text_calls

    def test_tenant_b_query_does_not_observe_tenant_a_id(self):
        """Each query request must carry the calling tenant's id, not the prior caller's."""
        km = _RecordingKM()

        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-1")
        with TestClient(_build_app(km, ctx_a), raise_server_exceptions=False) as ca:
            r = ca.get("/knowledge/query?q=alpha")
            assert r.status_code == 200

        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-2")
        with TestClient(_build_app(km, ctx_b), raise_server_exceptions=False) as cb:
            r = cb.get("/knowledge/query?q=bravo")
            assert r.status_code == 200

        # km.query_calls is in-order: A first then B; each carries its own id.
        assert km.query_calls == [("alpha", "tenant-A"), ("bravo", "tenant-B")]


class TestKnowledgeManagerStrictPostureRejectsMissingTenant:
    """Strict posture refuses to write when tenant_id is absent."""

    def test_ingest_text_strict_posture_rejects_missing_tenant_id(self, tmp_path, monkeypatch):
        """Direct KnowledgeManager.ingest_text without tenant_id raises under research."""
        from hi_agent.contracts.errors import TenantScopeError
        from hi_agent.knowledge.graph_renderer import GraphRenderer
        from hi_agent.knowledge.knowledge_manager import KnowledgeManager
        from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
        from hi_agent.knowledge.wiki import KnowledgeWiki
        from hi_agent.memory.long_term import LongTermMemoryGraph

        # Build under dev so we can construct without a tenant_id; then flip
        # to research posture for the actual ingest call.
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        wiki = KnowledgeWiki(str(tmp_path / "wiki"))
        user_store = UserKnowledgeStore(str(tmp_path / "user"))
        graph = LongTermMemoryGraph()
        renderer = GraphRenderer(graph)
        km = KnowledgeManager(
            wiki=wiki, user_store=user_store, graph=graph, renderer=renderer
        )

        # Now flip to strict posture and expect the write path to refuse.
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        with pytest.raises(TenantScopeError, match="tenant_id"):
            km.ingest_text("oops", "content")
        with pytest.raises(TenantScopeError, match="tenant_id"):
            km.ingest_structured([{"content": "fact"}])

    def test_ingest_text_dev_posture_accepts_missing_tenant_id(self, tmp_path, monkeypatch):
        """Dev posture remains permissive (warn-only)."""
        from hi_agent.knowledge.graph_renderer import GraphRenderer
        from hi_agent.knowledge.knowledge_manager import KnowledgeManager
        from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
        from hi_agent.knowledge.wiki import KnowledgeWiki
        from hi_agent.memory.long_term import LongTermMemoryGraph

        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        wiki = KnowledgeWiki(str(tmp_path / "wiki"))
        user_store = UserKnowledgeStore(str(tmp_path / "user"))
        graph = LongTermMemoryGraph()
        renderer = GraphRenderer(graph)
        km = KnowledgeManager(
            wiki=wiki, user_store=user_store, graph=graph, renderer=renderer
        )
        # Should not raise — dev posture accepts missing tenant_id.
        page_id = km.ingest_text("foo", "bar")
        assert page_id == "foo"


class TestAnnotationStrengthening:
    """The `# scope: process-internal` annotation is strengthened (W33 T-9'/T-10')."""

    def test_wiki_module_carries_strengthened_annotation(self):
        """WikiPage's class body carries the explicit "store row carries tenant_id" wording."""
        from hi_agent.knowledge import wiki as _wiki_mod

        src = _wiki_mod.__file__
        with open(src, encoding="utf-8") as fh:
            content = fh.read()
        # Required parts of the strengthened annotation.
        assert "# scope: process-internal" in content
        assert "value object only" in content
        assert "SqliteKnowledgeGraphBackend row" in content
        assert "ingest pipeline rejects an absent tenant_id" in content

    def test_entry_module_carries_strengthened_annotation(self):
        """KnowledgeEntry's class body carries the strengthened annotation."""
        from hi_agent.knowledge import entry as _entry_mod

        src = _entry_mod.__file__
        with open(src, encoding="utf-8") as fh:
            content = fh.read()
        assert "# scope: process-internal" in content
        assert "value object only" in content
        assert "SqliteKnowledgeGraphBackend row" in content
        assert "ingest pipeline rejects an absent tenant_id" in content
