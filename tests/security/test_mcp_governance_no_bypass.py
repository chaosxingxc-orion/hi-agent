"""Security contract tests for /mcp/tools/call governance — Arch-4.

Verifies that:
1. An unregistered MCP tool returns a governed "capability_not_found" error
   and does NOT invoke the raw mcp_server.call_tool() path.
2. A permission-denied tool does not invoke the raw path either.

Mock scope: Only CapabilityInvoker (external execution) and GovernedToolExecutor
are mocked/stubbed to isolate the HTTP handler logic.  mcp_server.call_tool is
monitored to ensure it is never called.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from hi_agent.capability.governance import (
    CapabilityNotFoundError,
    PermissionDeniedError,
)
from hi_agent.server.routes_tools_mcp import handle_mcp_tools_call
from hi_agent.server.tenant_context import TenantContext, reset_tenant_context, set_tenant_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_TENANT_CTX = TenantContext(
    tenant_id="test_tenant",
    user_id="test_user",
    session_id="test_session",
    auth_method="api_key",
)


def _make_request(body: dict, *, mcp_server: object | None = None) -> MagicMock:
    """Build a minimal Starlette-like Request mock for handle_mcp_tools_call."""
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.state.principal = "test_principal"
    request.state.session_id = "test_session"
    request.app.state.auth_posture = "dev_risk_open"

    # _mcp_server attribute on agent_server
    server_mock = MagicMock()
    server_mock._mcp_server = mcp_server

    # builder stubs for GovernedToolExecutor construction
    server_mock._builder.readiness.return_value = {}
    server_mock._builder.build_capability_registry.return_value = MagicMock()
    server_mock._builder.build_invoker.return_value = MagicMock()

    request.app.state.agent_server = server_mock
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unregistered_tool_returns_capability_not_found_no_raw_call():
    """Calling an unregistered MCP tool must return a 404 governed error.

    The raw mcp_server.call_tool() must NOT be invoked — the fallback bypass
    was removed in Arch-4.
    """
    mcp_server = MagicMock()
    request = _make_request({"name": "nonexistent_tool", "arguments": {}}, mcp_server=mcp_server)

    token = set_tenant_context(_TEST_TENANT_CTX)
    try:
        with (
            patch("hi_agent.capability.governance.GovernedToolExecutor") as mock_executor_cls,
            patch(
                "hi_agent.server.runtime_mode_resolver.resolve_runtime_mode",
                return_value="dev",
            ),
        ):
            # Simulate the executor raising CapabilityNotFoundError
            instance = mock_executor_cls.return_value
            instance.invoke.side_effect = CapabilityNotFoundError("nonexistent_tool not registered")

            response = asyncio.run(handle_mcp_tools_call(request))
    finally:
        reset_tenant_context(token)

    body = json.loads(response.body)
    assert response.status_code == 404
    assert body.get("error") == "capability_not_found"
    assert body.get("isError") is True
    # Raw mcp_server.call_tool must never have been called
    mcp_server.call_tool.assert_not_called()


def test_permission_denied_does_not_invoke_raw_path():
    """A permission-denied tool must return 403 without touching raw mcp_server.call_tool."""
    mcp_server = MagicMock()
    request = _make_request({"name": "restricted_tool", "arguments": {}}, mcp_server=mcp_server)

    token = set_tenant_context(_TEST_TENANT_CTX)
    try:
        with (
            patch("hi_agent.capability.governance.GovernedToolExecutor") as mock_executor_cls,
            patch(
                "hi_agent.server.runtime_mode_resolver.resolve_runtime_mode",
                return_value="dev",
            ),
        ):
            instance = mock_executor_cls.return_value
            instance.invoke.side_effect = PermissionDeniedError("principal lacks permission")

            response = asyncio.run(handle_mcp_tools_call(request))
    finally:
        reset_tenant_context(token)

    body = json.loads(response.body)
    assert response.status_code == 403
    assert body.get("isError") is True
    mcp_server.call_tool.assert_not_called()


def test_missing_mcp_server_returns_503():
    """When no mcp_server is configured the handler must return 503 immediately."""
    request = _make_request({"name": "any_tool"}, mcp_server=None)

    token = set_tenant_context(_TEST_TENANT_CTX)
    try:
        response = asyncio.run(handle_mcp_tools_call(request))
    finally:
        reset_tenant_context(token)

    body = json.loads(response.body)
    assert response.status_code == 503
    assert "mcp_server_not_configured" in body.get("error", "")
