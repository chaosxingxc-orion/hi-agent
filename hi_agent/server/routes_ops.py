"""HTTP route handlers for long-running operation handles (G-8).

Routes (registered in app.py):
    GET  /long-ops/{op_id}        -- Retrieve op handle by ID
    POST /long-ops/{op_id}/cancel -- Cancel an active op
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.server.tenant_context import require_tenant_context


async def handle_get_long_op(request: Request) -> JSONResponse:
    """GET /long-ops/{op_id} — return current op handle state."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    op_id = request.path_params["op_id"]
    server = request.app.state.agent_server
    coord = getattr(server, "op_coordinator", None)
    if coord is None:
        return JSONResponse({"error": "op_coordinator_not_configured"}, status_code=503)
    handle = coord.get(op_id)
    if handle is None:
        return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
    # Tenant scope filter: OpHandle.tenant_id is populated when the op is
    # submitted under an authenticated context.  Empty tenant_id is allowed
    # for back-compat with already-running ops; Wave 10.3 will tighten this
    # under Posture.is_strict.
    handle_tenant = getattr(handle, "tenant_id", "")
    if handle_tenant and handle_tenant != ctx.tenant_id:
        return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
    return JSONResponse(
        {
            "op_id": handle.op_id,
            "backend": handle.backend,
            "status": handle.status,
            "artifacts_uri": handle.artifacts_uri,
            "submitted_at": handle.submitted_at,
            "heartbeat_at": handle.heartbeat_at,
            "completed_at": handle.completed_at,
            "error": handle.error,
        }
    )


async def handle_cancel_long_op(request: Request) -> JSONResponse:
    """POST /long-ops/{op_id}/cancel — cancel an active op."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    op_id = request.path_params["op_id"]
    server = request.app.state.agent_server
    coord = getattr(server, "op_coordinator", None)
    if coord is None:
        return JSONResponse({"error": "op_coordinator_not_configured"}, status_code=503)
    # Tenant scope filter: check ownership before cancel.
    handle = coord.get(op_id)
    if handle is not None:
        handle_tenant = getattr(handle, "tenant_id", "")
        if handle_tenant and handle_tenant != ctx.tenant_id:
            return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
    ok = coord.cancel(op_id)
    if not ok:
        return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
    return JSONResponse({"cancelled": True, "op_id": op_id})
