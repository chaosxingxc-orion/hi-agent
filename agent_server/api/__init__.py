"""agent_server.api — northbound HTTP surface (W23 Phase 1, W24 Track I, W24-O)."""
from __future__ import annotations

from fastapi import FastAPI

from agent_server import AGENT_SERVER_API_VERSION
from agent_server.api.middleware.tenant_context import TenantContextMiddleware
from agent_server.api.routes_artifacts import build_router as _build_artifacts_router
from agent_server.api.routes_gates import build_router as _build_gates_router
from agent_server.api.routes_manifest import build_router as _build_manifest_router
from agent_server.api.routes_mcp_tools import build_router as _build_mcp_tools_router
from agent_server.api.routes_runs import build_router as _build_runs_router
from agent_server.api.routes_runs_extended import (
    build_router as _build_runs_extended_router,
)
from agent_server.api.routes_skills_memory import (
    build_router as _build_skills_memory_router,
)
from agent_server.facade.artifact_facade import ArtifactFacade
from agent_server.facade.event_facade import EventFacade
from agent_server.facade.manifest_facade import ManifestFacade
from agent_server.facade.run_facade import RunFacade

__all__ = ["build_app"]


def build_app(
    *,
    run_facade: RunFacade,
    event_facade: EventFacade | None = None,
    artifact_facade: ArtifactFacade | None = None,
    manifest_facade: ManifestFacade | None = None,
    include_mcp_tools: bool = True,
    include_skills_memory: bool = True,
    include_gates: bool = True,
) -> FastAPI:
    """Construct the agent_server ASGI app with routes + middleware wired.

    Parameters
    ----------
    run_facade:
        Pre-constructed :class:`RunFacade` whose injected callables bind
        to the kernel (real or stub). Routes never see the kernel
        directly — they only ever talk to the facade.
    event_facade:
        Optional facade backing /v1/runs/{id}/cancel and
        /v1/runs/{id}/events. Required for those routes to be wired.
    artifact_facade:
        Optional facade backing /v1/runs/{id}/artifacts and
        /v1/artifacts/{artifact_id}. Required for those routes to be wired.
    manifest_facade:
        Optional facade backing /v1/manifest. Required for that route to
        be wired.
    include_mcp_tools:
        When True (default), wire GET /v1/mcp/tools + POST /v1/mcp/tools/{name}
        (W24-O).
    include_skills_memory:
        When True (default), wire POST /v1/skills + POST /v1/memory/write
        (W24-P).
    include_gates:
        When True (default), wire POST /v1/gates/{gate_id}/decide.
    """
    app = FastAPI(
        title="agent_server northbound facade",
        version=AGENT_SERVER_API_VERSION,
    )
    app.add_middleware(TenantContextMiddleware)
    app.include_router(_build_runs_router(run_facade=run_facade))
    if event_facade is not None:
        app.include_router(
            _build_runs_extended_router(event_facade=event_facade)
        )
    if artifact_facade is not None:
        app.include_router(
            _build_artifacts_router(artifact_facade=artifact_facade)
        )
    if manifest_facade is not None:
        app.include_router(
            _build_manifest_router(manifest_facade=manifest_facade)
        )
    if include_mcp_tools:
        app.include_router(_build_mcp_tools_router())
    if include_skills_memory:
        app.include_router(_build_skills_memory_router())
    if include_gates:
        app.include_router(_build_gates_router())
    return app
