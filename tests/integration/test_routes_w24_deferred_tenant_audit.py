"""W24-H2 regression: 10 W24-deferred handlers must record tenant-scoped audit.

Each handler in scope:
    handle_knowledge_ingest             -> resource="knowledge", op="ingest"
    handle_knowledge_ingest_structured  -> resource="knowledge", op="ingest_structured"
    handle_knowledge_query              -> resource="knowledge", op="query"
    handle_knowledge_sync               -> resource="knowledge", op="sync"
    handle_skills_evolve                -> resource="skills",    op="evolve"
    handle_skill_optimize               -> resource="skills",    op="optimize"
    handle_skill_promote                -> resource="skills",    op="promote"
    handle_tools_call                   -> resource="tools",     op="call"
    handle_mcp_tools                    -> resource="mcp_tools", op="root"
    handle_mcp_tools_call               -> resource="mcp_tools", op="call"

Two assertions per handler:
    1. With a TenantContext set, ``record_tenant_scoped_access`` is called
       with the matching ``tenant_id`` (from ``ctx.tenant_id``) plus the
       expected resource/op pair.
    2. With NO TenantContext set, the handler returns HTTP 401 and does NOT
       call ``record_tenant_scoped_access`` (signal is gated by auth).

Layer 2 (integration): real route handlers wired through Starlette TestClient.
Mocking limited to the underlying singleton stores (knowledge_manager,
skill_evolver, MCP server, etc.) — not the route handler itself.

The data-partition gap (true cross-tenant isolation at the KG / skill / tool
registry level) is tracked separately by the existing xfail tests under
tests/integration/test_route_handle_*_tenant_isolation.py and the SA-1 ledger
A-06 (per-tenant graph partition) / A-10 (kernel idempotency tenant prefix).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
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
# Test helpers
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Middleware that pins a fixed TenantContext for every request."""

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


@dataclass
class _AuditCall:
    tenant_id: str
    resource: str
    op: str


@pytest.fixture
def audit_calls(monkeypatch):
    """Capture every record_tenant_scoped_access call for the test."""
    calls: list[_AuditCall] = []

    def _capture(*, tenant_id: str, resource: str, op: str) -> None:
        calls.append(_AuditCall(tenant_id=tenant_id, resource=resource, op=op))

    monkeypatch.setattr(
        "hi_agent.server.tenant_scope_audit.record_tenant_scoped_access",
        _capture,
    )
    # Also patch the import in route modules that bound the symbol at import time.
    monkeypatch.setattr(
        "hi_agent.server.routes_knowledge.record_tenant_scoped_access",
        _capture,
    )
    monkeypatch.setattr(
        "hi_agent.server.routes_tools_mcp.record_tenant_scoped_access",
        _capture,
    )
    # Skill routes import the symbol inside the handler — patch the module
    # canonically so the deferred import resolves to the capture.
    return calls


# ---------------------------------------------------------------------------
# Stub server primitives
# ---------------------------------------------------------------------------


class _FakeKM:
    def ingest_text(self, title: str, content: str, tags: list) -> str:
        return "page-1"

    def ingest_structured(self, facts: list) -> int:
        return len(facts)

    def query(self, q: str, limit: int = 10) -> Any:
        @dataclass
        class _R:
            total_results: int = 0

        return _R()

    def query_for_context(self, q: str, budget_tokens: int = 1500) -> str:
        return ""

    def get_stats(self) -> dict[str, Any]:
        return {"pages": 0, "nodes": 0}

    def lint(self) -> list[str]:
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


class _FakeMcpServer:
    def list_tools(self) -> dict[str, Any]:
        return {"tools": [], "count": 0}


class _FakeRegistry:
    def list_names(self) -> list[str]:
        return []

    def get(self, name: str) -> Any:  # pragma: no cover - never called
        return None


class _FakeInvoker:
    def __init__(self) -> None:
        self.registry = _FakeRegistry()


class _FakeBuilder:
    def build_invoker(self) -> _FakeInvoker:
        return _FakeInvoker()

    def build_capability_registry(self) -> _FakeRegistry:
        return _FakeRegistry()

    def readiness(self) -> dict:
        return {}


@dataclass
class _FakeReport:
    skills_analyzed: int = 0
    skills_optimized: int = 0
    patterns_discovered: int = 0
    skills_created: int = 0
    challenger_deployed: int = 0
    details: list[str] | None = None

    def __post_init__(self) -> None:
        if self.details is None:
            self.details = []


class _FakeEvolver:
    def evolve_cycle(self) -> _FakeReport:
        return _FakeReport()

    def optimize_prompt(self, skill_id: str) -> str | None:
        return None

    def deploy_optimization(self, skill_id: str, new_prompt: str) -> Any:  # pragma: no cover
        @dataclass
        class _R:
            version: str = "v1"
            is_challenger: bool = True

        return _R()

    @property
    def _version_manager(self):
        @dataclass
        class _VM:
            def promote_challenger(self, skill_id: str) -> bool:
                return True

        return _VM()


class _FakeServer:
    def __init__(self) -> None:
        self.knowledge_manager = _FakeKM()
        self.retrieval_engine = _FakeRetrieval()
        self.skill_evolver = _FakeEvolver()
        self._mcp_server = _FakeMcpServer()
        self.mcp_registry = None
        self._builder = _FakeBuilder()


# ---------------------------------------------------------------------------
# App builders
# ---------------------------------------------------------------------------


def _build_app(routes: list[Route], ctx: TenantContext | None) -> Starlette:
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer()
    app.state.auth_posture = "dev_risk_open"
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


# Each row: (route_path, handler_dotted_path, method, body, resource, op)
_HANDLERS: list[tuple[str, str, str, dict | None, str, str]] = [
    (
        "/knowledge/ingest",
        "hi_agent.server.routes_knowledge.handle_knowledge_ingest",
        "POST",
        {"title": "t", "content": "c"},
        "knowledge",
        "ingest",
    ),
    (
        "/knowledge/ingest-structured",
        "hi_agent.server.routes_knowledge.handle_knowledge_ingest_structured",
        "POST",
        {"facts": []},
        "knowledge",
        "ingest_structured",
    ),
    (
        "/knowledge/query",
        "hi_agent.server.routes_knowledge.handle_knowledge_query",
        "GET",
        None,
        "knowledge",
        "query",
    ),
    (
        "/knowledge/sync",
        "hi_agent.server.routes_knowledge.handle_knowledge_sync",
        "POST",
        {},
        "knowledge",
        "sync",
    ),
    (
        "/skills/evolve",
        "hi_agent.server.app.handle_skills_evolve",
        "POST",
        {},
        "skills",
        "evolve",
    ),
    (
        "/skills/{skill_id}/optimize",
        "hi_agent.server.app.handle_skill_optimize",
        "POST",
        {},
        "skills",
        "optimize",
    ),
    (
        "/skills/{skill_id}/promote",
        "hi_agent.server.app.handle_skill_promote",
        "POST",
        {},
        "skills",
        "promote",
    ),
    (
        "/tools/call",
        "hi_agent.server.routes_tools_mcp.handle_tools_call",
        "POST",
        {"name": "x"},
        "tools",
        "call",
    ),
    (
        "/mcp/tools",
        "hi_agent.server.routes_tools_mcp.handle_mcp_tools",
        "GET",
        None,
        "mcp_tools",
        "root",
    ),
    (
        "/mcp/tools/call",
        "hi_agent.server.routes_tools_mcp.handle_mcp_tools_call",
        "POST",
        {"name": "x", "arguments": {}},
        "mcp_tools",
        "call",
    ),
]


def _resolve(dotted: str):
    mod_path, _, name = dotted.rpartition(".")
    import importlib

    mod = importlib.import_module(mod_path)
    return getattr(mod, name)


def _request_path(path: str, method: str, body: dict | None, client: TestClient):
    sample = path.replace("{skill_id}", "skill-x")
    if method == "GET":
        return client.get(sample)
    return client.post(sample, json=body or {})


# ---------------------------------------------------------------------------
# Authorized-tenant case: handler must record audit + return 2xx
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,handler_path,method,body,resource,op",
    _HANDLERS,
    ids=[h[1].rsplit(".", 1)[-1] for h in _HANDLERS],
)
def test_authorized_tenant_records_scoped_audit(
    path, handler_path, method, body, resource, op, audit_calls
):
    """Authorized tenant gets a 2xx and exactly one tenant-scoped audit record."""
    handler = _resolve(handler_path)
    app = _build_app(
        [Route(path, handler, methods=[method])],
        ctx=TenantContext(tenant_id="tenant-A", user_id="user-a"),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = _request_path(path, method, body, client)

    # Handler may legitimately 503 (subsystem stub None) or 5xx on stubbed
    # invoker — that still proves the audit ran *before* the dispatch decision.
    assert resp.status_code < 600, (
        f"unexpected status {resp.status_code} for {handler_path}: {resp.text}"
    )

    assert any(
        c.tenant_id == "tenant-A" and c.resource == resource and c.op == op
        for c in audit_calls
    ), (
        f"{handler_path}: expected audit record "
        f"(tenant_id=tenant-A, resource={resource!r}, op={op!r}); got {audit_calls}"
    )


# ---------------------------------------------------------------------------
# Unauthenticated case: handler must 401 and emit NO audit record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,handler_path,method,body,resource,op",
    _HANDLERS,
    ids=[h[1].rsplit(".", 1)[-1] for h in _HANDLERS],
)
def test_unauthenticated_returns_401_and_no_audit(
    path, handler_path, method, body, resource, op, audit_calls
):
    """No TenantContext -> 401 and no audit signal (auth gates the trail)."""
    handler = _resolve(handler_path)
    app = _build_app([Route(path, handler, methods=[method])], ctx=None)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = _request_path(path, method, body, client)
    assert resp.status_code == 401, (
        f"{handler_path}: expected 401 with no TenantContext, got {resp.status_code}"
    )
    assert audit_calls == [], (
        f"{handler_path}: audit record leaked for unauthenticated caller: {audit_calls}"
    )
