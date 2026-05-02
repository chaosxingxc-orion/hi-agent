"""Tenant isolation: handle_knowledge_ingest_structured must reject cross-tenant access (AX-F F1).

Gap confirmed in W21 audit: knowledge_manager is a server-wide singleton.
Tenant B can ingest structured facts into the same global graph as Tenant A.
Tests are xfail until W22 implements per-tenant KG scoping.

Layer 2 — Integration: real route handlers, no MagicMock on subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.server.routes_knowledge import (
    handle_knowledge_ingest_structured,
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


class _GlobalFactStore:
    """Knowledge manager stub simulating the CURRENT (broken) global-store behavior.

    ingest_structured writes facts to a shared list with no tenant tagging.
    """

    def __init__(self):
        self._facts: list[dict] = []

    def ingest_structured(self, facts: list) -> int:
        self._facts.extend(facts)
        return len(facts)

    def all_facts(self) -> list[dict]:
        return list(self._facts)

    def get_stats(self):
        return {"pages": 0, "nodes": len(self._facts)}

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
        Route(
            "/knowledge/ingest-structured",
            handle_knowledge_ingest_structured,
            methods=["POST"],
        ),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(km)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.mark.xfail(
    reason=(
        "handle_knowledge_ingest_structured: knowledge_manager is a global singleton "
        "with no per-tenant partitioning (W21 gap). Tenant B's facts are stored in "
        "the same graph as Tenant A's, enabling cross-tenant data pollution. "
        "Fix in W22: tag each fact with tenant_id and filter by tenant on reads."
    ),
    strict=False,
    expiry_wave="Wave 30",
)
class TestKnowledgeIngestStructuredTenantIsolation:
    """POST /knowledge/ingest-structured must isolate facts by tenant (AX-F F1)."""

    def test_tenant_b_facts_do_not_pollute_tenant_a_graph(self):
        """Facts ingested by Tenant B must not appear in Tenant A's graph.

        Currently FAILS: all facts land in the same global list regardless of
        which tenant performed the ingest call.
        """
        km = _GlobalFactStore()

        ctx_a = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")
        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")

        tenant_a_secret = {"subject": "A-secret", "predicate": "has", "object": "A-private-data"}
        tenant_b_fact = {"subject": "B-fact", "predicate": "knows", "object": "B-data"}

        app_a = _build_app(km, ctx_a)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            resp = ca.post(
                "/knowledge/ingest-structured",
                json={"facts": [tenant_a_secret]},
            )
            assert resp.status_code == 201, f"Tenant A ingest failed: {resp.text}"

        app_b = _build_app(km, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post(
                "/knowledge/ingest-structured",
                json={"facts": [tenant_b_fact]},
            )
            assert resp.status_code == 201, f"Tenant B ingest failed: {resp.text}"

        # In a correctly isolated system, the global store should never hold
        # facts from two different tenants without tagging.
        all_facts = km.all_facts()
        # Both facts are present in the shared store — isolation gap confirmed.
        a_subjects = [f.get("subject") for f in all_facts]
        assert "A-secret" not in a_subjects, (
            "Tenant A's secret fact is in the shared global store, "
            "accessible without tenant context filter. "
            f"All stored facts: {all_facts}"
        )

    def test_structured_ingest_tags_facts_with_tenant_id(self):
        """Every ingested fact must carry tenant_id as metadata.

        Currently FAILS: ingest_structured receives no tenant_id argument;
        facts are stored as plain dicts without tenant attribution.
        """
        km = _GlobalFactStore()
        ctx = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")

        app = _build_app(km, ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/knowledge/ingest-structured",
                json={"facts": [{"subject": "X", "predicate": "is", "object": "Y"}]},
            )
            assert resp.status_code == 201

        stored = km.all_facts()
        assert len(stored) == 1
        fact = stored[0]
        assert "tenant_id" in fact, (
            f"Stored fact missing tenant_id field: {fact}. "
            "Correct implementation must tag facts with tenant_id on ingest."
        )
        assert fact["tenant_id"] == "isolation-tenant-A", (
            f"fact[tenant_id]={fact.get('tenant_id')!r}, "
            "expected 'isolation-tenant-A'"
        )
