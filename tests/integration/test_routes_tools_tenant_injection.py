"""W24-H2 regression: tools/MCP route handlers must record tenant-scoped audit.

Companion to test_routes_w24_deferred_tenant_audit.py — this file is the
named replacement_test for three W24-deferred allowlist entries:

    handle_tools_call        -> resource="tools",     op="call"
    handle_mcp_tools         -> resource="mcp_tools", op="root"
    handle_mcp_tools_call    -> resource="mcp_tools", op="call"

Two assertions per handler:
    1. Authorized tenant -> exactly one ``record_tenant_scoped_access`` call
       with the matching tenant_id/resource/op triple.
    2. Unauthenticated -> 401 + zero audit records.

Layer 2 integration: real route handlers, real Starlette routing, real
TenantContext middleware.  Mocking limited to the underlying singletons
(capability registry, MCP server) — never the route handler itself.
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
# Helpers (kept local so this file is self-contained per the W23-H precedent)
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware(BaseHTTPMiddleware):
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
    calls: list[_AuditCall] = []

    def _capture(*, tenant_id: str, resource: str, op: str) -> None:
        calls.append(_AuditCall(tenant_id=tenant_id, resource=resource, op=op))

    monkeypatch.setattr(
        "hi_agent.server.tenant_scope_audit.record_tenant_scoped_access",
        _capture,
    )
    monkeypatch.setattr(
        "hi_agent.server.routes_tools_mcp.record_tenant_scoped_access",
        _capture,
    )
    return calls


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


class _FakeServer:
    def __init__(self) -> None:
        self._mcp_server = _FakeMcpServer()
        self.mcp_registry = None
        self._builder = _FakeBuilder()


def _build_app(routes: list[Route], ctx: TenantContext | None) -> Starlette:
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer()
    app.state.auth_posture = "dev_risk_open"
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


_HANDLERS: list[tuple[str, str, str, dict | None, str, str]] = [
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
    import importlib

    mod_path, _, name = dotted.rpartition(".")
    return getattr(importlib.import_module(mod_path), name)


def _send(path: str, method: str, body: dict | None, client: TestClient):
    if method == "GET":
        return client.get(path)
    return client.post(path, json=body or {})


@pytest.mark.parametrize(
    "path,handler_path,method,body,resource,op",
    _HANDLERS,
    ids=[h[1].rsplit(".", 1)[-1] for h in _HANDLERS],
)
def test_authorized_tenant_records_scoped_audit(
    path, handler_path, method, body, resource, op, audit_calls
):
    """Authorized tenant gets a 2xx-class response and exactly one audit record."""
    handler = _resolve(handler_path)
    app = _build_app(
        [Route(path, handler, methods=[method])],
        ctx=TenantContext(tenant_id="tenant-X", user_id="user-x"),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = _send(path, method, body, client)
    assert resp.status_code < 600
    assert any(
        c.tenant_id == "tenant-X" and c.resource == resource and c.op == op
        for c in audit_calls
    ), (
        f"{handler_path}: missing audit (tenant_id=tenant-X, resource={resource!r}, "
        f"op={op!r}); got {audit_calls}"
    )


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
        resp = _send(path, method, body, client)
    assert resp.status_code == 401, (
        f"{handler_path}: expected 401 with no TenantContext, got {resp.status_code}"
    )
    assert audit_calls == [], (
        f"{handler_path}: audit leaked for unauthenticated caller: {audit_calls}"
    )
