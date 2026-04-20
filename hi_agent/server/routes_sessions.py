"""Session management HTTP route handlers.

Handlers:
    handle_list_sessions      GET   /sessions
    handle_get_session_runs   GET   /sessions/{session_id}/runs
    handle_patch_session      PATCH /sessions/{session_id}
"""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.server.tenant_context import TenantContext, require_tenant_context


async def handle_list_sessions(request: Request) -> JSONResponse:
    """List all active sessions belonging to the current user."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server: Any = request.app.state.agent_server
    store = server.session_store
    sessions = store.list_active(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    return JSONResponse(
        {
            "sessions": [
                {
                    "session_id": s.session_id,
                    "name": s.name,
                    "status": s.status,
                    "created_at": s.created_at,
                }
                for s in sessions
            ]
        }
    )


async def handle_get_session_runs(request: Request) -> JSONResponse:
    """Return all runs associated with a specific session."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    sid = request.path_params["session_id"]
    server: Any = request.app.state.agent_server
    store = server.session_store
    if not store.validate_ownership(sid, ctx.tenant_id, ctx.user_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    manager = server.run_manager
    session_ctx = TenantContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        session_id=sid,
        team_id=ctx.team_id,
        roles=ctx.roles,
    )
    runs = manager.list_runs(workspace=session_ctx)
    return JSONResponse({"runs": [_run_summary(r) for r in runs]})


async def handle_patch_session(request: Request) -> JSONResponse:
    """Archive or rename a session."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    sid = request.path_params["session_id"]
    server: Any = request.app.state.agent_server
    store = server.session_store
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    if body.get("status") == "archived":
        try:
            store.archive(sid, tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        except PermissionError:
            return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"session_id": sid, "status": body.get("status", "")})


def _run_summary(run: Any) -> dict:
    """Produce a minimal JSON-safe summary of a ManagedRun."""
    return {
        "run_id": run.run_id,
        "state": run.state,
        "session_id": run.session_id,
        "created_at": getattr(run, "created_at", ""),
    }
