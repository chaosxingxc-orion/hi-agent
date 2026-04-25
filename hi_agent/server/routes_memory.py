"""Memory route handlers extracted from app.py (E-4 refactor)."""

from __future__ import annotations

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi_agent.auth.operation_policy import require_operation
from hi_agent.server.tenant_context import require_tenant_context

logger = logging.getLogger(__name__)


def _resolve_profile_id(ctx: object, body: dict) -> str:
    """Derive a tenant-scoped profile_id from the request body and auth context.

    Rules:
    - If the body provides no ``profile_id``, return ``""`` (caller uses server default).
    - If the body provides ``"default"``, return it as-is (safe sentinel).
    - If the body provides a tenant-scoped value (starts with ``tenant_id::`` or equals
      ``tenant_id``), accept it.
    - Otherwise, discard it, log a warning, and return ``""`` so the caller falls back
      to the server's default memory manager.

    Returns:
        A non-empty string when the body supplies a valid tenant-scoped profile_id;
        ``""`` otherwise (causes callers to use ``server.memory_manager``).
    """
    tenant_id = getattr(ctx, "tenant_id", None) or ""
    body_profile = body.get("profile_id", "")
    if not body_profile:
        return ""  # no profile requested — use server default
    if body_profile == "default":
        return body_profile
    # Accept if scoped to the authenticated tenant
    if tenant_id and (
        body_profile.startswith(tenant_id + "::") or body_profile == tenant_id
    ):
        return body_profile
    # Body profile_id is not scoped to this tenant — discard it
    logger.warning(
        "memory_route: ignoring body profile_id %r; not scoped to tenant %r",
        body_profile,
        tenant_id or "(anonymous)",
    )
    return ""


async def handle_memory_dream(request: Request) -> JSONResponse:
    """Trigger dream consolidation (short-term -> mid-term)."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = _resolve_profile_id(ctx, body)
    if profile_id and profile_id != "default":
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
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = _resolve_profile_id(ctx, body)
    if profile_id and profile_id != "default":
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
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = _resolve_profile_id(ctx, body)
    if profile_id and profile_id != "default":
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
