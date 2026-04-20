"""Routes for the hi_agent_global cross-profile read layer (G-1).

Endpoints:
    GET /profiles/hi_agent_global/memory/l3  -- Global L3 memory summary
    GET /profiles/hi_agent_global/skills     -- Global skills listing
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse


async def handle_global_l3_summary(request: Request) -> JSONResponse:
    """Return a summary of the global L3 memory directory.

    GET /profiles/hi_agent_global/memory/l3
    """
    mgr = _get_profile_dir_manager(request)
    if mgr is None:
        return JSONResponse({"error": "profile_manager_not_available"}, status_code=503)
    path = mgr.get_global_memory_l3()
    if not path.exists():
        return JSONResponse({"nodes": 0, "edges": 0, "path": str(path), "exists": False})
    files = list(path.glob("*.json")) if path.is_dir() else []
    return JSONResponse({"files": len(files), "path": str(path), "exists": True})


async def handle_global_skills(request: Request) -> JSONResponse:
    """Return the list of skill directory names under the global profile.

    GET /profiles/hi_agent_global/skills
    """
    mgr = _get_profile_dir_manager(request)
    if mgr is None:
        return JSONResponse({"error": "profile_manager_not_available"}, status_code=503)
    path = mgr.get_global_skills()
    if not path.exists():
        return JSONResponse({"skills": [], "path": str(path)})
    skill_dirs = [d.name for d in path.iterdir() if d.is_dir()] if path.is_dir() else []
    return JSONResponse({"skills": skill_dirs, "path": str(path)})


def _get_profile_dir_manager(request: Request):  # type: ignore[return]
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
    except Exception:
        return None
