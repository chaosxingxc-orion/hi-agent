"""Memory route handlers extracted from app.py (E-4 refactor)."""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi_agent.auth.operation_policy import require_operation
from hi_agent.server.tenant_context import require_tenant_context


async def handle_memory_dream(request: Request) -> JSONResponse:
    """Trigger dream consolidation (short-term -> mid-term)."""
    try:
        require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = body.get("profile_id", "")
    if profile_id:
        # K-9: Build a per-request scoped manager for profile deployments.
        try:
            from hi_agent.config.builder import SystemBuilder

            _builder = SystemBuilder()
            manager = _builder.build_memory_lifecycle_manager(profile_id=profile_id)
        except Exception as _build_exc:
            return JSONResponse(
                {"error": f"profile_manager_build_failed: {_build_exc}"}, status_code=500
            )
    else:
        manager = server.memory_manager

    if manager is None:
        return JSONResponse({"error": "memory_not_configured"}, status_code=503)

    result = manager.trigger_dream(body.get("date"))
    return JSONResponse(result)


@require_operation("memory.consolidate")
async def handle_memory_consolidate(request: Request) -> JSONResponse:
    """Trigger consolidation (mid-term -> long-term)."""
    try:
        require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = body.get("profile_id", "")
    if profile_id:
        # K-9: Build a per-request scoped manager for profile deployments.
        try:
            from hi_agent.config.builder import SystemBuilder

            _builder = SystemBuilder()
            manager = _builder.build_memory_lifecycle_manager(profile_id=profile_id)
        except Exception as _build_exc:
            return JSONResponse(
                {"error": f"profile_manager_build_failed: {_build_exc}"}, status_code=500
            )
    else:
        manager = server.memory_manager

    if manager is None:
        return JSONResponse({"error": "memory_not_configured"}, status_code=503)

    result = manager.trigger_consolidation(body.get("days", 7))
    return JSONResponse(result)


async def handle_memory_status(request: Request) -> JSONResponse:
    """Return memory tier status."""
    try:
        require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = body.get("profile_id", "")
    if profile_id:
        # K-9: Build a per-request scoped manager for profile deployments.
        try:
            from hi_agent.config.builder import SystemBuilder

            _builder = SystemBuilder()
            manager = _builder.build_memory_lifecycle_manager(profile_id=profile_id)
        except Exception as _build_exc:
            return JSONResponse(
                {"error": f"profile_manager_build_failed: {_build_exc}"}, status_code=500
            )
    else:
        manager = server.memory_manager

    if manager is None:
        return JSONResponse({"error": "memory_not_configured"}, status_code=503)

    result = manager.get_status()
    return JSONResponse(result)


routes = [
    Route("/memory/dream", handle_memory_dream, methods=["POST"]),
    Route("/memory/consolidate", handle_memory_consolidate, methods=["POST"]),
    Route("/memory/status", handle_memory_status, methods=["GET"]),
]
