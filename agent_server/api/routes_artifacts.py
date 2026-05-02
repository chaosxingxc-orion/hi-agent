"""Northbound HTTP route handlers for /v1/artifacts (W24 Track I-B, W27-L15).

Per R-AS-1 this module imports ONLY from agent_server.contracts and
agent_server.facade — never from hi_agent.* directly. Per R-AS-4 every
handler reads the tenant context from request.state (set by
TenantContextMiddleware), never from the request body.

# tdd-red-sha: 3bc0a83
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from agent_server.contracts.errors import ContractError
from agent_server.contracts.tenancy import TenantContext
from agent_server.facade.artifact_facade import ArtifactFacade


def build_router(*, artifact_facade: ArtifactFacade) -> APIRouter:
    """Wire list + get artifact handlers against the injected facade."""
    router = APIRouter(tags=["artifacts"])

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

    # tdd-red-sha: 3bc0a83
    @router.get("/v1/runs/{run_id}/artifacts")
    async def list_run_artifacts(
        run_id: str, request: Request
    ) -> JSONResponse:
        ctx = _ctx(request)
        try:
            records = artifact_facade.list_for_run(ctx, run_id)
        except ContractError as exc:
            return _error_response(exc)
        # tenant_id=ctx.tenant_id is enforced inside the facade.
        return JSONResponse(
            status_code=200,
            content={
                "run_id": run_id,
                "tenant_id": ctx.tenant_id,
                "artifacts": [_serialize(r) for r in records],
            },
        )

    # tdd-red-sha: 3bc0a83
    @router.get("/v1/artifacts/{artifact_id}")
    async def get_artifact(
        artifact_id: str, request: Request
    ) -> JSONResponse:
        ctx = _ctx(request)
        try:
            record = artifact_facade.get(ctx, artifact_id)
        except ContractError as exc:
            return _error_response(exc)
        return JSONResponse(status_code=200, content=_serialize(record))

    # tdd-red-sha: 326a0e1e
    @router.post("/v1/artifacts")
    async def post_artifact(request: Request) -> JSONResponse:
        ctx = _ctx(request)
        try:
            body: dict[str, Any] = await request.json()
        except Exception as exc:  # pragma: no cover - defensive
            err = ContractError("invalid JSON body", detail=str(exc), http_status=400)
            return _error_response(err)
        run_id = str(body.get("run_id", "")).strip()
        artifact_type = str(body.get("artifact_type", "")).strip()
        content = body.get("content")
        metadata: dict[str, Any] = dict(body.get("metadata", {}) or {})
        if not run_id:
            err = ContractError(
                "run_id is required",
                tenant_id=ctx.tenant_id,
                detail="missing run_id",
                http_status=400,
            )
            return _error_response(err)
        if not artifact_type:
            err = ContractError(
                "artifact_type is required",
                tenant_id=ctx.tenant_id,
                detail="missing artifact_type",
                http_status=400,
            )
            return _error_response(err)
        if content is None:
            err = ContractError(
                "content is required",
                tenant_id=ctx.tenant_id,
                detail="missing content",
                http_status=400,
            )
            return _error_response(err)
        try:
            result = artifact_facade.register(
                ctx,
                run_id=run_id,
                artifact_type=artifact_type,
                content=content,
                metadata=metadata,
            )
        except ContractError as exc:
            return _error_response(exc)
        from datetime import UTC, datetime
        return JSONResponse(
            status_code=201,
            content={
                "artifact_id": result["artifact_id"],
                "created_at": datetime.now(UTC).isoformat(),
                "tenant_id": ctx.tenant_id,
                "run_id": run_id,
            },
        )

    return router


def _serialize(record: dict) -> dict:
    """Strip non-JSON fields and convert bytes values to safe representations."""
    out: dict = {}
    for k, v in record.items():
        if isinstance(v, (bytes, bytearray)):
            out[k] = {"__bytes_len__": len(v)}
        else:
            out[k] = v
    return out
