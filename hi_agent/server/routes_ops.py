"""HTTP route handlers for long-running operation handles (G-8).

Routes (registered in app.py):
    GET  /long-ops/{op_id}        -- Retrieve op handle by ID
    POST /long-ops/{op_id}/cancel -- Cancel an active op
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.config.posture import Posture
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
    handle_tenant = getattr(handle, "tenant_id", "")
    if Posture.from_env().is_strict:
        if not handle_tenant or handle_tenant != ctx.tenant_id:
            return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
    else:
        # dev: back-compat — empty-tenant op visible; log + count for observability
        if handle_tenant and handle_tenant != ctx.tenant_id:
            return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
        if not handle_tenant:
            try:
                from hi_agent.observability.fallback import record_fallback

                record_fallback("op", reason="empty_tenant_back_compat_visible", run_id=op_id)
            except Exception:  # rule7-exempt: expiry_wave="Wave 22" replacement_test: wave22-tests
                pass
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
        if Posture.from_env().is_strict:
            if not handle_tenant or handle_tenant != ctx.tenant_id:
                return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
        else:
            # dev: back-compat — empty-tenant op visible; log + count for observability
            if handle_tenant and handle_tenant != ctx.tenant_id:
                return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
            if not handle_tenant:
                try:
                    from hi_agent.observability.fallback import record_fallback

                    record_fallback("op", reason="empty_tenant_back_compat_visible", run_id=op_id)
                except Exception:  # rule7-exempt: expiry_wave="Wave 22"
                    pass
    ok = coord.cancel(op_id)
    if not ok:
        return JSONResponse({"error": "not_found", "op_id": op_id}, status_code=404)
    return JSONResponse({"cancelled": True, "op_id": op_id})


async def handle_ops_drain(request: Request) -> JSONResponse:
    """POST /ops/drain — initiate graceful drain; waits for in-flight runs to complete.

    If runs do not reach terminal within timeout_s, forcibly fails remaining
    active runs via run_manager.shutdown() so callers always see terminal state.
    """
    server = request.app.state.agent_server
    run_manager = getattr(server, "run_manager", None)
    if run_manager is None:
        return JSONResponse({"error": "run_manager_not_configured"}, status_code=503)

    server._draining = True

    timeout_s = float(request.query_params.get("timeout", "30"))
    drained = run_manager.drain(timeout_s=timeout_s)

    if not drained:
        # Graceful wait expired — forcibly fail remaining active runs so they
        # reach terminal state (callers can observe this via /runs/{id}).
        run_manager.shutdown(timeout=5.0)

    return JSONResponse({
        "status": "drained" if drained else "forced",
        "draining": True,
    }, status_code=200)
