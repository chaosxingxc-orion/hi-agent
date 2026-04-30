"""Northbound HTTP route handler for /v1/manifest (W24 Track I-C).

Per R-AS-1 this module imports ONLY from agent_server.contracts and
agent_server.facade — never from hi_agent.* directly. Per R-AS-4 every
handler reads the tenant context from request.state (set by
TenantContextMiddleware), never from the request body.

# tdd-red-sha: 3bc0a83
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from agent_server.contracts.errors import ContractError
from agent_server.contracts.tenancy import TenantContext
from agent_server.facade.manifest_facade import ManifestFacade


def build_router(*, manifest_facade: ManifestFacade) -> APIRouter:
    """Wire the manifest endpoint against the injected facade."""
    router = APIRouter(tags=["manifest"])

    def _ctx(request: Request) -> TenantContext:
        ctx = getattr(request.state, "tenant_context", None)
        if not isinstance(ctx, TenantContext):  # defensive — middleware guards
            raise ContractError("tenant context missing", detail="middleware")
        return ctx

    @router.get("/v1/manifest")
    async def get_manifest(request: Request) -> JSONResponse:
        # Tenant context is required to enforce the auth middleware contract;
        # the manifest body itself is tenant-agnostic at v1.
        _ = _ctx(request)
        return JSONResponse(
            status_code=200,
            content=manifest_facade.manifest(),
        )

    return router
