"""Ops DLQ route handlers.

Endpoints:
    GET  /ops/dlq                       -- List dead-lettered runs
    POST /ops/dlq/{run_id}/requeue      -- Requeue a dead-lettered run
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse


async def handle_list_dlq(request: Request) -> JSONResponse:
    """GET /ops/dlq -- list all dead-lettered runs.

    Optional query param: tenant_id (filter by tenant).
    Returns 200 with a JSON list of DLQ records.
    """
    server = request.app.state.agent_server
    run_queue = getattr(server, "_run_queue", None)
    if run_queue is None:
        return JSONResponse({"error": "run_queue_not_configured"}, status_code=503)
    tenant_id = request.query_params.get("tenant_id")
    records = run_queue.list_dlq(tenant_id=tenant_id)
    return JSONResponse({"dead_lettered_runs": records})


async def handle_requeue_from_dlq(request: Request) -> JSONResponse:
    """POST /ops/dlq/{run_id}/requeue -- requeue a dead-lettered run.

    Returns 200 on success, 404 if run_id is not in the DLQ.
    """
    server = request.app.state.agent_server
    run_queue = getattr(server, "_run_queue", None)
    if run_queue is None:
        return JSONResponse({"error": "run_queue_not_configured"}, status_code=503)
    run_id: str = request.path_params["run_id"]
    requeued = run_queue.requeue_from_dlq(run_id)
    if not requeued:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)
    return JSONResponse({"status": "requeued", "run_id": run_id})
