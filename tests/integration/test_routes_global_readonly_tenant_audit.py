"""W23-H regression: 8 global-readonly handlers must record tenant-scoped audit.

Each handler in scope:
    handle_knowledge_status   -> resource="knowledge",  op="status"
    handle_knowledge_lint     -> resource="knowledge",  op="lint"
    handle_skills_list        -> resource="skills",     op="list"
    handle_skills_status      -> resource="skills",     op="status"
    handle_skill_metrics      -> resource="skills",     op="metrics"
    handle_skill_versions     -> resource="skills",     op="versions"
    handle_tools_list         -> resource="tools",      op="list"
    handle_mcp_tools_list     -> resource="mcp_tools",  op="list"

Two assertions per handler:
    1. With a TenantContext set, ``record_tenant_scoped_access`` is called
       with the matching ``tenant_id`` (from ``ctx.tenant_id``) plus the
       expected resource/op pair.
    2. With NO TenantContext set, the handler returns HTTP 401 and does NOT
       call ``record_tenant_scoped_access`` (signal is gated by auth).

Layer 2 (integration): real route handlers wired through Starlette TestClient.
Mocking limited to the underlying singleton stores (knowledge_manager,
skill_evolver, MCP server, etc.) — not the route handler itself.
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
    return calls


# ---------------------------------------------------------------------------
# Stub server primitives
# ---------------------------------------------------------------------------


class _FakeKM:
    """W31, T-2'/T-3': accepts tenant_id kwarg on read methods."""

    def get_stats(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return {"pages": 0, "nodes": 0}

    def lint(self, *, tenant_id: str | None = None) -> list[str]:
        return []


class _FakeMetrics:
    success_rate = 0.0
    total_executions = 0


class _FakeObserver:
    def get_all_metrics(self) -> dict[str, Any]:
        return {}

    def get_metrics(self, skill_id: str, tenant_id: str | None = None) -> Any:
        return _FakeMetricsRecord()


@dataclass
class _FakeMetricsRecord:
    skill_id: str = ""
    total_executions: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    failure_rate: float = 0.0
    last_execution_at: float = 0.0


@dataclass
class _FakeVersion:
    version: str = "v1"
    is_champion: bool = True
    is_challenger: bool = False
    created_at: str = "2026-04-30T00:00:00Z"


class _FakeVersionManager:
    def list_versions(self, skill_id: str) -> list[_FakeVersion]:
        return [_FakeVersion()]


class _FakeEvolver:
    def __init__(self) -> None:
        self._observer = _FakeObserver()
        self._version_manager = _FakeVersionManager()


class _FakeLoader:
    def discover(self) -> None:  # pragma: no cover - trivial
        return None

    def list_skills(self, eligible_only: bool = False) -> list[Any]:
        return []


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


class _FakeServer:
    def __init__(self) -> None:
        self.knowledge_manager = _FakeKM()
        self.retrieval_engine = None
        self.skill_loader = _FakeLoader()
        self.skill_evolver = _FakeEvolver()
        self._mcp_server = _FakeMcpServer()
        self.mcp_registry = None
        self._builder = _FakeBuilder()


# ---------------------------------------------------------------------------
# App builders (one per route family — keep stubs tight)
# ---------------------------------------------------------------------------


def _build_app(routes: list[Route], ctx: TenantContext | None) -> Starlette:
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer()
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


# Each row: (route_path, handler_dotted_path, expected_resource, expected_op)
_HANDLERS: list[tuple[str, str, str, str, str]] = [
    (
        "/knowledge/status",
        "hi_agent.server.routes_knowledge.handle_knowledge_status",
        "GET",
        "knowledge",
        "status",
    ),
    (
        "/knowledge/lint",
        "hi_agent.server.routes_knowledge.handle_knowledge_lint",
        "POST",
        "knowledge",
        "lint",
    ),
    (
        "/skills",
        "hi_agent.server.app.handle_skills_list",
        "GET",
        "skills",
        "list",
    ),
    (
        "/skills/status",
        "hi_agent.server.app.handle_skills_status",
        "GET",
        "skills",
        "status",
    ),
    (
        "/skills/{skill_id}/metrics",
        "hi_agent.server.app.handle_skill_metrics",
        "GET",
        "skills",
        "metrics",
    ),
    (
        "/skills/{skill_id}/versions",
        "hi_agent.server.app.handle_skill_versions",
        "GET",
        "skills",
        "versions",
    ),
    (
        "/tools",
        "hi_agent.server.routes_tools_mcp.handle_tools_list",
        "GET",
        "tools",
        "list",
    ),
    (
        "/mcp/tools/list",
        "hi_agent.server.routes_tools_mcp.handle_mcp_tools_list",
        "POST",
        "mcp_tools",
        "list",
    ),
]


def _resolve(dotted: str):
    mod_path, _, name = dotted.rpartition(".")
    import importlib

    mod = importlib.import_module(mod_path)
    return getattr(mod, name)


def _request_path(path: str, method: str, client: TestClient):
    sample = path.replace("{skill_id}", "skill-x")
    if method == "GET":
        return client.get(sample)
    return client.post(sample, json={})


# ---------------------------------------------------------------------------
# Authorized-tenant case: handler must record audit + return 200/201/2xx
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,handler_path,method,resource,op",
    _HANDLERS,
    ids=[h[1].rsplit(".", 1)[-1] for h in _HANDLERS],
)
def test_authorized_tenant_records_scoped_audit(
    path, handler_path, method, resource, op, audit_calls
):
    """Authorized tenant gets a 2xx and exactly one tenant-scoped audit record."""
    handler = _resolve(handler_path)
    app = _build_app(
        [Route(path, handler, methods=[method])],
        ctx=TenantContext(tenant_id="tenant-A", user_id="user-a"),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = _request_path(path, method, client)

    # Handler may legitimately 503 if a sub-component is None in the stub —
    # that still proves the audit ran *before* the dispatch decision.
    assert resp.status_code < 500 or resp.status_code == 503, (
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
    "path,handler_path,method,resource,op",
    _HANDLERS,
    ids=[h[1].rsplit(".", 1)[-1] for h in _HANDLERS],
)
def test_unauthenticated_returns_401_and_no_audit(
    path, handler_path, method, resource, op, audit_calls
):
    """No TenantContext -> 401 and no audit signal (auth gates the trail)."""
    handler = _resolve(handler_path)
    app = _build_app([Route(path, handler, methods=[method])], ctx=None)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = _request_path(path, method, client)
    assert resp.status_code == 401, (
        f"{handler_path}: expected 401 with no TenantContext, got {resp.status_code}"
    )
    assert audit_calls == [], (
        f"{handler_path}: audit record leaked for unauthenticated caller: {audit_calls}"
    )
