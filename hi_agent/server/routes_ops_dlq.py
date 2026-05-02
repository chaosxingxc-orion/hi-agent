"""Ops DLQ route handlers.

Endpoints:
    GET  /ops/dlq                       -- List dead-lettered runs
    POST /ops/dlq/{run_id}/requeue      -- Requeue a dead-lettered run

Tenant scope (W31, T-1' fix):
    The previous implementation read ``tenant_id`` from query_params with no
    auth check, which leaked DLQ rows across tenants when the param was
    omitted. The handler now derives ``tenant_id`` from the authenticated
    ``TenantContext`` set by AuthMiddleware. Under research/prod posture a
    missing context fails closed with 401; under dev posture it falls back
    to ``__anonymous__`` with a WARNING log (back-compat).
"""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.config.posture import Posture
from hi_agent.server.tenant_context import get_tenant_context

_logger = logging.getLogger(__name__)


_DEV_FALLBACK_TENANT_ID = "__anonymous__"


async def handle_list_dlq(request: Request) -> JSONResponse:
    """GET /ops/dlq -- list dead-lettered runs scoped to the authenticated tenant.

    Tenant scope:
        Under research/prod posture, the request must carry an authenticated
        ``TenantContext`` (set by AuthMiddleware). Without one the handler
        returns 401. The query parameter ``tenant_id`` is ignored — the
        scope is taken from the authenticated context, not caller-supplied
        input, to prevent cross-tenant data leaks (W31 T-1').

        Under dev posture, missing context falls back to ``__anonymous__``
        with a WARNING log so existing dev fixtures continue to work.

    Returns:
        200 with ``{"dead_lettered_runs": [...]}``, scoped to the caller's
        tenant.
        401 when research/prod posture is set and no TenantContext is
        attached to the request.
        503 when the run queue is not configured.
    """
    server = request.app.state.agent_server
    run_queue = getattr(server, "_run_queue", None)
    if run_queue is None:
        return JSONResponse({"error": "run_queue_not_configured"}, status_code=503)

    posture = Posture.from_env()
    ctx = get_tenant_context()
    if ctx is None or not ctx.tenant_id:
        if posture.is_strict:
            return JSONResponse(
                {"error": "authentication_required"}, status_code=401
            )
        # dev: back-compat — fall back to anonymous with WARNING for observability.
        _logger.warning(
            "/ops/dlq: missing TenantContext under dev posture; falling back to "
            "%r. Configure HI_AGENT_API_KEY and authenticate to scope properly.",
            _DEV_FALLBACK_TENANT_ID,
        )
        tenant_id = _DEV_FALLBACK_TENANT_ID
    else:
        tenant_id = ctx.tenant_id

    records = run_queue.list_dlq(tenant_id=tenant_id)
    return JSONResponse({"dead_lettered_runs": records})


async def handle_requeue_from_dlq(request: Request) -> JSONResponse:
    """POST /ops/dlq/{run_id}/requeue -- requeue a dead-lettered run.

    Tenant scope (W31, T-1' fix): under research/prod posture, the request
    must carry an authenticated TenantContext. The handler enforces that
    ``run_id`` belongs to the caller's tenant before requeue.

    Returns 200 on success, 401 when strict posture and no TenantContext,
    404 if run_id is not in the DLQ or belongs to another tenant.
    """
    server = request.app.state.agent_server
    run_queue = getattr(server, "_run_queue", None)
    if run_queue is None:
        return JSONResponse({"error": "run_queue_not_configured"}, status_code=503)

    posture = Posture.from_env()
    ctx = get_tenant_context()
    if ctx is None or not ctx.tenant_id:
        if posture.is_strict:
            return JSONResponse(
                {"error": "authentication_required"}, status_code=401
            )
        _logger.warning(
            "/ops/dlq/{run_id}/requeue: missing TenantContext under dev posture; "
            "falling back to %r. Configure HI_AGENT_API_KEY and authenticate "
            "to scope properly.",
            _DEV_FALLBACK_TENANT_ID,
        )
        tenant_id = _DEV_FALLBACK_TENANT_ID
    else:
        tenant_id = ctx.tenant_id

    run_id: str = request.path_params["run_id"]

    # Ownership check: only requeue rows that belong to the caller's tenant.
    own_rows = run_queue.list_dlq(tenant_id=tenant_id)
    own_run_ids = {row.get("run_id") for row in own_rows}
    if run_id not in own_run_ids:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)

    requeued = run_queue.requeue_from_dlq(run_id)
    if not requeued:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)
    return JSONResponse({"status": "requeued", "run_id": run_id})
