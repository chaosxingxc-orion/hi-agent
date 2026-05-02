"""Northbound HTTP route handlers for /v1/mcp/tools (W24-O).

Provides a workspace-scoped MCP tools proxy:

    GET  /v1/mcp/tools          — list available MCP tools for this workspace
    POST /v1/mcp/tools/{name}   — invoke a specific MCP tool

Per R-AS-1 this module imports ONLY from agent_server.contracts and
agent_server.facade — never from hi_agent.* directly. Per R-AS-4 every
handler reads the tenant context from request.state (set by
TenantContextMiddleware), never from the request body.

# tdd-red-sha: e2c8c34a
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from agent_server.contracts.errors import ContractError, NotFoundError
from agent_server.contracts.tenancy import TenantContext


def build_router() -> APIRouter:
    """Build the /v1/mcp/tools router.

    No facade injection required at this maturity level: the router
    returns a workspace-scoped stub response.  When a real MCPFacade
    is available it can be injected here as a keyword argument without
    breaking the caller contract.
    """
    router = APIRouter(prefix="/v1/mcp", tags=["mcp-tools"])

    def _error_response(exc: ContractError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": type(exc).__name__,
                "message": str(exc),
                "tenant_id": exc.tenant_id,
                "detail": exc.detail,
            },
        )

    def _ctx(request: Request) -> TenantContext:
        ctx = getattr(request.state, "tenant_context", None)
        if not isinstance(ctx, TenantContext):  # defensive — middleware guards
            raise ContractError("tenant context missing", detail="middleware")
        return ctx

    # tdd-red-sha: e2c8c34a
    @router.get("/tools")
    async def list_mcp_tools(request: Request) -> JSONResponse:
        """List MCP tools available for this workspace.

        Returns the set of MCP tools registered and accessible to the
        requesting tenant's workspace.  At L1 maturity this always
        returns an empty list; a real MCPFacade will be wired in at L2.
        """
        try:
            ctx = _ctx(request)
        except ContractError as exc:
            return _error_response(exc)
        return JSONResponse(
            status_code=200,
            content={
                "tenant_id": ctx.tenant_id,
                "tools": [],
                "count": 0,
            },
        )

    # tdd-red-sha: e2c8c34a
    @router.post("/tools/{tool_name}")
    async def invoke_mcp_tool(tool_name: str, request: Request) -> JSONResponse:
        """Invoke a specific MCP tool by name.

        The tool must be registered and accessible to the requesting
        tenant's workspace.  Returns the tool invocation result.
        At L1 maturity, unknown tool names return 404.
        """
        try:
            ctx = _ctx(request)
        except ContractError as exc:
            return _error_response(exc)

        try:
            await request.json()
        except Exception as exc:  # pragma: no cover — defensive
            err = ContractError("invalid JSON body", detail=str(exc), http_status=400)
            return _error_response(err)

        if not tool_name or not tool_name.strip():
            err = ContractError(
                "tool_name is required",
                tenant_id=ctx.tenant_id,
                detail="empty tool name in path",
                http_status=400,
            )
            return _error_response(err)

        # At L1 maturity no tools are registered; return 404 for any invocation.
        # A real MCPFacade will resolve and dispatch here.
        exc = NotFoundError(
            f"MCP tool {tool_name!r} not found",
            tenant_id=ctx.tenant_id,
            detail="no tools registered at this maturity level",
        )
        return _error_response(exc)

    return router
