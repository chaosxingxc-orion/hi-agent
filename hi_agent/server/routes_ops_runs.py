"""Operator diagnostic endpoints for run inspection.

Handlers:
    handle_ops_run_full     GET /ops/runs/{run_id}/full
    handle_ops_run_diagnose GET /ops/runs/{run_id}/diagnose
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.server.tenant_context import require_tenant_context

logger = logging.getLogger(__name__)


async def handle_ops_run_full(request: Request) -> JSONResponse:
    """Single-call aggregated run state for operator diagnosis.

    Query parameters:
        workspace (str, required): Tenant workspace ID.

    Returns a combined view of: state, stage, created_at, finished_at,
    events_summary, failure_classification, trace_id, and
    operator_actions_available.
    """
    try:
        require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    run_id = request.path_params["run_id"]
    workspace = request.query_params.get("workspace")
    if not workspace:
        return JSONResponse(
            {"error": "missing_required_param", "param": "workspace"}, status_code=400
        )

    server: Any = request.app.state.agent_server

    run_store = getattr(server, "_run_store", None)
    if run_store is None:
        return JSONResponse({"error": "run_store_not_configured"}, status_code=503)

    run = run_store.get_for_tenant(run_id, workspace)
    if run is None:
        return JSONResponse(
            {"error": "not_found", "run_id": run_id, "workspace": workspace}, status_code=404
        )

    event_store = getattr(server, "_event_store", None)
    events: list[dict] = []
    if event_store is not None and hasattr(event_store, "get_events"):
        try:
            events = event_store.get_events(run_id, offset=0, limit=50)
        except Exception as exc:
            logger.warning("handle_ops_run_full: get_events failed for %s: %s", run_id, exc)

    state = run.status
    actions: list[str] = []
    if state not in ("completed", "failed", "cancelled"):
        actions.append("cancel")
    if state == "failed":
        actions.extend(["inspect_events", "retry"])
    if "inspect_events" not in actions:
        actions.append("inspect_events")

    finished_at_val = getattr(run, "finished_at", None)
    finished_at_str: str | None = None
    if finished_at_val:
        finished_at_str = str(finished_at_val)

    return JSONResponse(
        {
            "run_id": run_id,
            "workspace": workspace,
            "state": state,
            "stage": None,  # RunRecord does not carry current_stage; sourced from run_manager
            "created_at": str(run.created_at),
            "finished_at": finished_at_str,
            "events_summary": {
                "count": len(events),
                "last_event": events[-1] if events else None,
            },
            "failure_classification": run.error_summary or None,
            "trace_id": None,
            "operator_actions_available": list(dict.fromkeys(actions)),
        }
    )


async def handle_ops_run_diagnose(request: Request) -> JSONResponse:
    """Stuck-run diagnosis: lease state, last event, DLQ candidacy.

    Query parameters:
        workspace (str, required): Tenant workspace ID.
    """
    try:
        require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    run_id = request.path_params["run_id"]
    workspace = request.query_params.get("workspace")
    if not workspace:
        return JSONResponse(
            {"error": "missing_required_param", "param": "workspace"}, status_code=400
        )

    server: Any = request.app.state.agent_server

    run_store = getattr(server, "_run_store", None)
    if run_store is None:
        return JSONResponse({"error": "run_store_not_configured"}, status_code=503)

    run = run_store.get_for_tenant(run_id, workspace)
    if run is None:
        return JSONResponse(
            {"error": "not_found", "run_id": run_id, "workspace": workspace}, status_code=404
        )

    event_store = getattr(server, "_event_store", None)
    events: list[dict] = []
    if event_store is not None and hasattr(event_store, "get_events"):
        try:
            events = event_store.get_events(run_id, offset=0, limit=10)
        except Exception as exc:
            logger.warning("handle_ops_run_diagnose: get_events failed for %s: %s", run_id, exc)

    state = run.status
    last_event = events[-1] if events else None
    dlq_candidate = state not in ("completed", "cancelled") and len(events) > 0

    if state == "running" and not last_event:
        diagnosis = "Run appears stuck — no events recorded and state is running"
    elif state in ("completed", "cancelled"):
        diagnosis = "Run has reached a terminal state"
    else:
        diagnosis = "Run progressing normally"

    return JSONResponse(
        {
            "run_id": run_id,
            "workspace": workspace,
            "state": state,
            "last_event": last_event,
            "dlq_candidate": dlq_candidate,
            "diagnosis": diagnosis,
        }
    )
