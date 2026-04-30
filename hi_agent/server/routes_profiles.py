"""Routes for the hi_agent_global cross-profile read layer (G-1).

Endpoints:
    GET /profiles/hi_agent_global/memory/l3  -- Global L3 memory summary
    GET /profiles/hi_agent_global/skills     -- Global skills listing

DX-5: Absolute host filesystem paths are never returned in JSON responses.
``path_token`` is the last two path components (parent.name/name), which
identifies the location within the hi-agent data layout without leaking
the operator's absolute directory structure.
"""

from __future__ import annotations

import logging
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.server.tenant_context import require_tenant_context

logger = logging.getLogger(__name__)


async def handle_global_l3_summary(request: Request) -> JSONResponse:
    """Return a summary of the global L3 memory directory.

    GET /profiles/hi_agent_global/memory/l3
    """
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    # Global profile routes are admin-only: require tenant_id == "admin" or is_admin flag.
    if not getattr(ctx, "is_admin", False) and getattr(ctx, "tenant_id", "") != "admin":
        return JSONResponse({"error": "admin_required"}, status_code=403)
    mgr = _get_profile_dir_manager(request)
    if mgr is None:
        return JSONResponse({"error": "profile_manager_not_available"}, status_code=503)
    path = mgr.get_global_memory_l3()
    logger.debug("global_l3_summary: absolute path %s", path)
    path_token = _path_token(path)
    if not path.exists():
        return JSONResponse({"nodes": 0, "edges": 0, "path_token": path_token, "exists": False})
    files = list(path.glob("*.json")) if path.is_dir() else []
    return JSONResponse({"files": len(files), "path_token": path_token, "exists": True})


async def handle_global_skills(request: Request) -> JSONResponse:
    """Return the list of skill directory names under the global profile.

    GET /profiles/hi_agent_global/skills
    """
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    # Global profile routes are admin-only: require tenant_id == "admin" or is_admin flag.
    if not getattr(ctx, "is_admin", False) and getattr(ctx, "tenant_id", "") != "admin":
        return JSONResponse({"error": "admin_required"}, status_code=403)
    mgr = _get_profile_dir_manager(request)
    if mgr is None:
        return JSONResponse({"error": "profile_manager_not_available"}, status_code=503)
    path = mgr.get_global_skills()
    logger.debug("global_skills: absolute path %s", path)
    path_token = _path_token(path)
    if not path.exists():
        return JSONResponse({"skills": [], "path_token": path_token})
    skill_dirs = [d.name for d in path.iterdir() if d.is_dir()] if path.is_dir() else []
    return JSONResponse({"skills": skill_dirs, "path_token": path_token})


def _path_token(path: Path) -> str:
    """Return a non-leaking path token (last two components) for JSON responses.

    Example: /home/user/.hi_agent/global/memory/l3 -> "memory/l3"
    This identifies the logical location without exposing the absolute host path.
    """
    parts = path.parts
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return path.name


def _get_profile_dir_manager(request: Request):  # type: ignore[return]  expiry_wave: Wave 27
    """Extract ProfileDirectoryManager from the server, if available."""
    server = getattr(request.app.state, "agent_server", None)
    if server is None:
        return None
    mgr = getattr(server, "profile_dir_manager", None)
    if mgr is not None:
        return mgr
    # Fallback: build one from the home default.
    try:
        from hi_agent.profile.manager import ProfileDirectoryManager

        return ProfileDirectoryManager()
    except Exception as exc:
        logger.warning("profile_manager_init_failed: %s", exc, exc_info=True)
        from hi_agent.observability.fallback import record_fallback

        record_fallback("capability", reason="profile_manager_init_failed", run_id="system")
        return None
