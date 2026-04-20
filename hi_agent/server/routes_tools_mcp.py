"""HTTP route handlers for /tools, /tools/call, /mcp/tools, /mcp/tools/list, /mcp/tools/call."""

from __future__ import annotations

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Tools (capability registry) endpoints
# ------------------------------------------------------------------


async def handle_tools_list(request: Request) -> JSONResponse:
    """Return all registered capabilities as a tool list.

    Response shape::

        {"tools": [{"name": "file_read", "description": "...", "parameters": {...}}, ...]}
    """
    server = request.app.state.agent_server
    try:
        invoker = server._builder.build_invoker()
        registry = invoker.registry
        tools = []
        for name in registry.list_names():
            spec = registry.get(name)
            tools.append(
                {
                    "name": name,
                    "description": getattr(spec, "description", ""),
                    "parameters": getattr(spec, "parameters", {}),
                }
            )
        return JSONResponse({"tools": tools, "count": len(tools)})
    except Exception as exc:
        logger.warning("handle_tools_list error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_tools_call(request: Request) -> JSONResponse:
    """Invoke a registered capability by name.

    Request body::

        {"name": "file_read", "arguments": {"path": "CLAUDE.md"}}

    Response shape::

        {"success": bool, "result": {...}}
    """
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    name = body.get("name")
    if not name:
        return JSONResponse({"error": "missing_name"}, status_code=400)
    arguments = body.get("arguments", {})

    from hi_agent.capability.governance import (
        ApprovalRequiredError,
        CapabilityDisabledError,
        CapabilityNotFoundError,
        CapabilityUnavailableError,
        GovernedToolExecutor,
        PermissionDeniedError,
        PolicyViolationError,
    )

    server = request.app.state.agent_server
    principal = getattr(request.state, "principal", "anonymous")
    session_id = getattr(request.state, "session_id", "")
    try:
        import os as _os_tc

        from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm_tc

        _env_tc = _os_tc.environ.get("HI_AGENT_ENV", "dev").lower()
        try:
            _readiness_tc = server._builder.readiness()
        except Exception:
            _readiness_tc = {}
        _runtime_mode_tc = _rrm_tc(_env_tc, _readiness_tc)
        _auth_posture_tc = getattr(request.app.state, "auth_posture", "dev_risk_open")
        if _auth_posture_tc == "degraded":
            return JSONResponse(
                {"success": False, "error": "Authentication not configured for production mode"},
                status_code=503,
            )
        invoker = server._builder.build_invoker()
        registry = server._builder.build_capability_registry()
        executor = GovernedToolExecutor(
            registry=registry, invoker=invoker, runtime_mode=_runtime_mode_tc
        )
        result = executor.invoke(
            name,
            arguments,
            principal=principal,
            session_id=session_id,
            source="http_tools",
        )
        return JSONResponse({"success": True, "result": result})
    except CapabilityNotFoundError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=404)
    except (CapabilityDisabledError, PermissionDeniedError) as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=403)
    except ApprovalRequiredError as exc:
        return JSONResponse(
            {"success": False, "error": str(exc), "capability_name": exc.capability_name},
            status_code=202,
        )
    except PolicyViolationError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)
    except CapabilityUnavailableError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=503)
    except Exception as exc:
        logger.warning("handle_tools_call error for %r: %s", name, exc)
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


# ------------------------------------------------------------------
# MCP tools endpoints
# ------------------------------------------------------------------


async def handle_mcp_tools(request: Request) -> JSONResponse:
    """Return all tools across registered MCP servers.

    Prefers _mcp_server (same data source as /mcp/tools/list) so all tool
    endpoints return a consistent view.
    """
    try:
        server = request.app.state.agent_server
        mcp_srv = getattr(server, "_mcp_server", None)
        if mcp_srv is not None:
            try:
                return JSONResponse(mcp_srv.list_tools())
            except Exception:
                pass
        # Fallback: registry-based listing
        mcp_reg = server.mcp_registry
        tools: list[dict] = []
        for srv in mcp_reg.list_servers():
            for tool_name in srv.get("tools", []):
                tools.append(
                    {
                        "server_id": srv["server_id"],
                        "tool": tool_name,
                        "capability_name": f"mcp.{srv['server_id']}.{tool_name}",
                    }
                )
        return JSONResponse({"tools": tools, "count": len(tools)})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "tools": [], "count": 0}, status_code=500)


async def handle_mcp_tools_list(request: Request) -> JSONResponse:
    """MCP tools/list — enumerate all registered tools with their input schemas.

    Returns an MCP-compatible response:
    {"tools": [{"name": str, "description": str, "inputSchema": {...}}]}
    """
    server = request.app.state.agent_server
    mcp_server = getattr(server, "_mcp_server", None)
    if mcp_server is None:
        return JSONResponse({"error": "mcp_server_not_configured"}, status_code=503)
    try:
        return JSONResponse(mcp_server.list_tools())
    except Exception as exc:
        logger.exception("handle_mcp_tools_list failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_mcp_tools_call(request: Request) -> JSONResponse:
    """MCP tools/call — invoke a named tool with arguments.

    Request body (flat form):
        {"name": "file_read", "arguments": {"path": "CLAUDE.md"}}

    Or JSON-RPC params envelope:
        {"params": {"name": "file_read", "arguments": {"path": "CLAUDE.md"}}}

    Returns an MCP-compatible content response:
        {"content": [{"type": "text", "text": str}], "isError": bool}
    """
    server = request.app.state.agent_server
    mcp_server = getattr(server, "_mcp_server", None)
    if mcp_server is None:
        return JSONResponse({"error": "mcp_server_not_configured"}, status_code=503)
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    params = body.get("params", {})
    name = body.get("name") or params.get("name")
    arguments = body.get("arguments", params.get("arguments", {}))
    if not name:
        return JSONResponse({"error": "missing_tool_name"}, status_code=400)
    from hi_agent.capability.governance import (
        ApprovalRequiredError,
        CapabilityDisabledError,
        CapabilityNotFoundError,
        CapabilityUnavailableError,
        GovernedToolExecutor,
        PermissionDeniedError,
        PolicyViolationError,
    )

    principal = getattr(request.state, "principal", "anonymous")
    session_id = getattr(request.state, "session_id", "")
    try:
        import os as _os_mc

        from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm_mc

        _env_mc = _os_mc.environ.get("HI_AGENT_ENV", "dev").lower()
        try:
            _readiness_mc = server._builder.readiness()
        except Exception:
            _readiness_mc = {}
        _runtime_mode_mc = _rrm_mc(_env_mc, _readiness_mc)
        _auth_posture_mc = getattr(request.app.state, "auth_posture", "dev_risk_open")
        if _auth_posture_mc == "degraded":
            return JSONResponse(
                {"isError": True, "error": "Authentication not configured for production mode"},
                status_code=503,
            )
        registry = server._builder.build_capability_registry()
        invoker = server._builder.build_invoker()
        executor = GovernedToolExecutor(
            registry=registry, invoker=invoker, runtime_mode=_runtime_mode_mc
        )
        result = executor.invoke(
            name,
            arguments or {},
            principal=principal,
            session_id=session_id,
            source="http_mcp",
        )
        return JSONResponse(result)
    except CapabilityNotFoundError:
        # Governance: never bypass to raw invoker — return a governed not-found error.
        logger.warning(
            "mcp_tools_call: capability_not_found tool=%r principal=%r session=%r",
            name,
            principal,
            session_id,
        )
        return JSONResponse(
            {"isError": True, "error": "capability_not_found", "tool": name},
            status_code=404,
        )
    except (CapabilityDisabledError, PermissionDeniedError) as exc:
        return JSONResponse({"isError": True, "error": str(exc)}, status_code=403)
    except ApprovalRequiredError as exc:
        return JSONResponse(
            {"isError": True, "error": str(exc), "capability_name": exc.capability_name},
            status_code=202,
        )
    except PolicyViolationError as exc:
        return JSONResponse({"isError": True, "error": str(exc)}, status_code=400)
    except CapabilityUnavailableError as exc:
        return JSONResponse({"isError": True, "error": str(exc)}, status_code=503)
    except Exception as exc:
        logger.exception("handle_mcp_tools_call failed for tool %r", name)
        return JSONResponse({"error": str(exc)}, status_code=500)
