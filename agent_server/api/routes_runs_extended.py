"""Northbound HTTP route handlers for cancel + events SSE (W24 Track I-A).

Per R-AS-1 this module imports ONLY from agent_server.contracts and
agent_server.facade — never from hi_agent.* directly. Per R-AS-4 every
handler reads the tenant context from request.state (set by
TenantContextMiddleware), never from the request body.

# tdd-red-sha: 3bc0a83
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, StreamingResponse

from agent_server.contracts.errors import ContractError
from agent_server.contracts.tenancy import TenantContext
from agent_server.facade.event_facade import EventFacade, render_sse_chunk

_TERMINAL_STATES = frozenset({"done", "failed", "cancelled", "completed"})


def build_router(*, event_facade: EventFacade) -> APIRouter:
    """Wire cancel + events handlers against the injected facade."""
    router = APIRouter(prefix="/v1/runs", tags=["runs-extended"])

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

    @router.post("/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request) -> JSONResponse:
        ctx = _ctx(request)
        try:
            status = event_facade.cancel(ctx, run_id)
        except ContractError as exc:
            return _error_response(exc)
        return JSONResponse(status_code=200, content=_status_dict(status))

    @router.get("/{run_id}/events")
    async def stream_events(run_id: str, request: Request):
        ctx = _ctx(request)
        # Verify the run is visible to this tenant before opening the stream.
        try:
            status = event_facade.assert_run_visible(ctx, run_id)
        except ContractError as exc:
            return _error_response(exc)

        async def _generator():
            try:
                events_iter = event_facade.iter_events(ctx, run_id)
            except ContractError:
                return
            for event in events_iter:
                yield render_sse_chunk(event)
                # Cooperate with the event loop so the client can disconnect.
                await asyncio.sleep(0)
            # If the run is terminal, we close after replay.
            if status.state in _TERMINAL_STATES:
                return

        return StreamingResponse(
            _generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return router


def _status_dict(status) -> dict:
    return {
        "tenant_id": status.tenant_id,
        "run_id": status.run_id,
        "state": status.state,
        "current_stage": status.current_stage,
        "llm_fallback_count": status.llm_fallback_count,
        "finished_at": status.finished_at,
    }
