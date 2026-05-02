"""Northbound HTTP route handler for POST /v1/gates/{gate_id}/decide.

Per R-AS-1 this module imports ONLY from agent_server.contracts and
agent_server.facade — never from hi_agent.* directly. W31-N (N.5)
introduced :class:`agent_server.contracts.gate.GateDecisionRequest` so
the previous deferred ``from hi_agent.contracts.gate_decision import
GateDecisionRequest`` is no longer required and has been removed. Per
R-AS-4 every handler reads the tenant context from request.state (set
by TenantContextMiddleware), never from the request body.

# tdd-red-sha: e2c8c34a
"""
from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from agent_server.contracts.errors import ContractError
from agent_server.contracts.gate import GateDecisionRequest
from agent_server.contracts.tenancy import TenantContext


def build_router() -> APIRouter:
    """Build the /v1/gates router."""
    router = APIRouter(prefix="/v1/gates", tags=["gates"])

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
    @router.post("/{gate_id}/decide")
    async def decide_gate(gate_id: str, request: Request) -> JSONResponse:
        """Record an approval or rejection decision for a gate.

        Body fields:
          run_id   — the run this gate belongs to (required)
          decision — "approved" | "rejected" (required)
          reason   — human-readable rationale (optional)
          decided_by — actor identity (optional)
        """
        try:
            ctx = _ctx(request)
        except ContractError as exc:
            return _error_response(exc)

        try:
            body: dict[str, Any] = await request.json()
        except Exception as exc:  # pragma: no cover — defensive
            err = ContractError("invalid JSON body", detail=str(exc))
            err.http_status = 400
            return _error_response(err)

        run_id = str(body.get("run_id", "")).strip()
        decision = str(body.get("decision", "")).strip()

        if not run_id:
            err = ContractError(
                "run_id is required",
                tenant_id=ctx.tenant_id,
                detail="missing run_id in request body",
            )
            err.http_status = 400
            return _error_response(err)

        if decision not in {"approved", "rejected"}:
            err = ContractError(
                f"decision must be 'approved' or 'rejected', got {decision!r}",
                tenant_id=ctx.tenant_id,
                detail="invalid decision value",
            )
            err.http_status = 400
            return _error_response(err)

        # Build the GateDecisionRequest contract object for downstream use.
        decided_at = str(body.get("decided_at", "")).strip()
        if not decided_at:
            decided_at = datetime.datetime.now(tz=datetime.UTC).isoformat()

        try:
            gate_req = GateDecisionRequest(
                gate_id=gate_id,
                run_id=run_id,
                tenant_id=ctx.tenant_id,
                decision=decision,
                reason=str(body.get("reason", "")),
                decided_by=str(body.get("decided_by", "")),
                decided_at=decided_at,
            )
        except ValueError as exc:
            err = ContractError(str(exc), tenant_id=ctx.tenant_id, detail="contract validation")
            err.http_status = 400
            return _error_response(err)

        return JSONResponse(
            status_code=200,
            content={
                "tenant_id": gate_req.tenant_id,
                "gate_id": gate_req.gate_id,
                "run_id": gate_req.run_id,
                "decision": gate_req.decision,
                "reason": gate_req.reason,
                "decided_by": gate_req.decided_by,
                "decided_at": gate_req.decided_at,
                "status": "recorded",
            },
        )

    return router
