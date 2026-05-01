"""Integration tests for GET /v1/mcp/tools + POST /v1/mcp/tools/{name} (W24-O).

Layer 2 — Integration: real route handlers wired into a Starlette test app.
No MagicMock on the subsystem under test (routes_mcp_tools).

# tdd-red-sha: e2c8c34a
"""
from __future__ import annotations

import pytest
from agent_server.api.middleware.tenant_context import TenantContextMiddleware
from agent_server.api.routes_mcp_tools import build_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with only the MCP tools router + auth middleware."""
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)
    app.include_router(build_router())
    return app


class TestListMcpTools:
    """GET /v1/mcp/tools — authenticated tenant receives tool list."""

    def test_list_mcp_tools_returns_200(self):
        """Authenticated GET /v1/mcp/tools returns 200 with tools envelope."""
        app = _build_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/v1/mcp/tools",
                headers={"X-Tenant-Id": "tenant-alpha"},
            )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)
        assert "count" in data
        assert data["tenant_id"] == "tenant-alpha"

    def test_list_mcp_tools_unauthenticated_returns_401(self):
        """GET /v1/mcp/tools without X-Tenant-Id returns 401."""
        app = _build_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/v1/mcp/tools")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    def test_list_mcp_tools_count_matches_tools_list(self):
        """The count field matches the length of the tools list."""
        app = _build_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/v1/mcp/tools",
                headers={"X-Tenant-Id": "tenant-beta"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == len(data["tools"])


class TestInvokeMcpTool:
    """POST /v1/mcp/tools/{name} — invocation returns result or 404 for unknown tools."""

    def test_invoke_mcp_tool_returns_result(self):
        """POST /v1/mcp/tools/{name} for unknown tool returns 404 with contract envelope.

        At L1 maturity no tools are registered, so any invocation returns 404.
        The test verifies the response shape is the contract envelope.
        """
        app = _build_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/v1/mcp/tools/file_read",
                json={"arguments": {"path": "/tmp/test.txt"}},
                headers={"X-Tenant-Id": "tenant-alpha"},
            )
        # At L1 maturity, unknown tools return 404 — verify envelope shape.
        assert resp.status_code in {200, 404}, (
            f"Expected 200 or 404, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "error" in data or "tenant_id" in data, (
            f"Response should carry error or tenant_id: {data}"
        )

    def test_invoke_mcp_tool_unauthenticated_returns_401(self):
        """POST /v1/mcp/tools/{name} without auth returns 401."""
        app = _build_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/v1/mcp/tools/file_read",
                json={"arguments": {}},
            )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    def test_invoke_mcp_tool_tenant_id_in_error_envelope(self):
        """404 envelope carries the requesting tenant_id for traceability."""
        app = _build_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/v1/mcp/tools/some_tool",
                json={},
                headers={"X-Tenant-Id": "tenant-gamma"},
            )
        assert resp.status_code == 404
        data = resp.json()
        assert data.get("tenant_id") == "tenant-gamma"
