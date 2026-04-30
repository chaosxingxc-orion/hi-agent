"""Northbound HTTP route handlers for /v1/runs (W23 Track F).

Per R-AS-1 this module imports ONLY from agent_server.contracts and
agent_server.facade — never from hi_agent.* directly. Per R-AS-4 every
handler reads the tenant context from request.state (set by
TenantContextMiddleware), never from the request body.

# tdd-red-sha: ddc0f0d
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from agent_server.contracts.errors import ContractError
from agent_server.contracts.run import RunRequest
from agent_server.contracts.tenancy import TenantContext
from agent_server.facade.run_facade import RunFacade


def build_router(*, run_facade: RunFacade) -> APIRouter:
    """Wire route handlers against an injected facade instance."""
    router = APIRouter(prefix="/v1/runs", tags=["runs"])

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

    @router.post("")
    async def post_run(request: Request) -> JSONResponse:
        ctx = _ctx(request)
        try:
            body: dict[str, Any] = await request.json()
        except Exception as exc:  # pragma: no cover - defensive
            err = ContractError("invalid JSON body", detail=str(exc))
            err.http_status = 400
            return _error_response(err)
        try:
            req = RunRequest(
                tenant_id=ctx.tenant_id,
                profile_id=str(body.get("profile_id", "")),
                goal=str(body.get("goal", "")),
                project_id=str(body.get("project_id", "")),
                run_id=str(body.get("run_id", "")),
                idempotency_key=str(body.get("idempotency_key", "")),
                metadata=dict(body.get("metadata", {}) or {}),
            )
            resp = run_facade.start(ctx, req)
        except ContractError as exc:
            return _error_response(exc)
        return JSONResponse(status_code=200, content=_run_response_to_dict(resp))

    @router.get("/{run_id}")
    async def get_run(run_id: str, request: Request) -> JSONResponse:
        ctx = _ctx(request)
        try:
            status = run_facade.status(ctx, run_id)
        except ContractError as exc:
            return _error_response(exc)
        return JSONResponse(status_code=200, content=_run_status_to_dict(status))

    @router.post("/{run_id}/signal")
    async def signal_run(run_id: str, request: Request) -> JSONResponse:
        ctx = _ctx(request)
        try:
            body: dict[str, Any] = await request.json()
        except Exception as exc:  # pragma: no cover - defensive
            err = ContractError("invalid JSON body", detail=str(exc))
            err.http_status = 400
            return _error_response(err)
        signal = str(body.get("signal", "")).strip()
        if not signal:
            err = ContractError(
                "signal is required",
                tenant_id=ctx.tenant_id,
                detail="missing signal",
            )
            err.http_status = 400
            return _error_response(err)
        try:
            status = run_facade.signal(
                ctx, run_id, signal, dict(body.get("payload", {}) or {})
            )
        except ContractError as exc:
            return _error_response(exc)
        return JSONResponse(status_code=200, content=_run_status_to_dict(status))

    return router


def _run_response_to_dict(resp: Any) -> dict[str, Any]:
    return {
        "tenant_id": resp.tenant_id,
        "run_id": resp.run_id,
        "state": resp.state,
        "current_stage": resp.current_stage,
        "started_at": resp.started_at,
        "finished_at": resp.finished_at,
        "metadata": dict(resp.metadata),
    }


def _run_status_to_dict(status: Any) -> dict[str, Any]:
    return {
        "tenant_id": status.tenant_id,
        "run_id": status.run_id,
        "state": status.state,
        "current_stage": status.current_stage,
        "llm_fallback_count": status.llm_fallback_count,
        "finished_at": status.finished_at,
    }
