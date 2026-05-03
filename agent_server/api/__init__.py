"""agent_server.api — northbound HTTP surface (W23 Phase 1, W24 Track I, W24-O, W31-N).

W31-N adds:
  * Optional ``idempotency_facade`` parameter on :func:`build_app` so the
    bootstrap (and only the bootstrap) can wire the
    :class:`IdempotencyMiddleware` while keeping the route-handler tests
    that don't need idempotency unchanged.
  * Built-in ``GET /v1/health`` route that returns ``{"status": "ok"}``
    so operators (and the W31-N1 acceptance test) can probe a serving
    instance with a single request.
  * (N.4) Optional ``tenant_event_emitter`` parameter on :func:`build_app`
    so the bootstrap can inject :func:`hi_agent.observability.spine_events.
    emit_tenant_context` without the middleware needing to import it.
  * (N.9) ``include_mcp_tools`` and ``include_skills_memory`` default to
    ``False`` because the corresponding routers are L1 stubs. The bootstrap
    flips them to True only when an idempotency_facade has been wired
    (production path) so dev-time builds stay quiet.
  * (N-12) ``AGENT_SERVER_API_VERSION`` re-exported via ``__all__``.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_server import AGENT_SERVER_API_VERSION
from agent_server.api.middleware.idempotency import register_idempotency_middleware
from agent_server.api.middleware.tenant_context import (
    TenantContextMiddleware,
    TenantEventEmitter,
)
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
from agent_server.facade.idempotency_facade import IdempotencyFacade
from agent_server.facade.manifest_facade import ManifestFacade
from agent_server.facade.run_facade import RunFacade

# W31-N (N-12): export AGENT_SERVER_API_VERSION through the package
# surface so callers don't need to reach into agent_server.config.
__all__ = ["AGENT_SERVER_API_VERSION", "build_app"]


def build_app(
    *,
    run_facade: RunFacade,
    event_facade: EventFacade | None = None,
    artifact_facade: ArtifactFacade | None = None,
    manifest_facade: ManifestFacade | None = None,
    idempotency_facade: IdempotencyFacade | None = None,
    idempotency_strict: bool | None = None,
    tenant_event_emitter: TenantEventEmitter | None = None,
    include_mcp_tools: bool = False,
    include_skills_memory: bool = False,
    include_gates: bool = True,
    lifespan=None,
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
    idempotency_facade:
        Optional :class:`IdempotencyFacade`. When provided (W31-N2), the
        :class:`IdempotencyMiddleware` is attached so retries with the
        same ``Idempotency-Key`` replay byte-identical responses. The
        production bootstrap always supplies it; route-level unit tests
        that don't care about idempotency leave it ``None``.
    idempotency_strict:
        Override for the strict flag of :class:`IdempotencyMiddleware`.
        ``None`` (the default) lets the middleware pick from the
        bootstrap-derived flag on the facade.
    tenant_event_emitter:
        Optional callable invoked once per request with the validated
        ``tenant_id`` (W31-N N.4). The bootstrap binds the real spine
        emitter; tests pass ``None`` and get a no-op default.
    include_mcp_tools:
        When True, wire GET /v1/mcp/tools + POST /v1/mcp/tools/{name}
        (L1 stub, W24-O). Defaults to False (W31-N N.9). The bootstrap
        opts in only when ``idempotency_facade`` is wired.
    include_skills_memory:
        When True, wire POST /v1/skills + POST /v1/memory/write (L1 stub,
        W24-P). Defaults to False (W31-N N.9). The bootstrap opts in
        only when ``idempotency_facade`` is wired.
    include_gates:
        When True (default), wire POST /v1/gates/{gate_id}/decide.
    lifespan:
        Optional FastAPI lifespan context manager (W32-A). When
        provided, attached as the FastAPI app's lifespan so the
        bootstrap can hook startup (rehydrate runs, warm caches) and
        shutdown (drain RunManager, close stores) into the ASGI
        startup/shutdown protocol. Tests and stub builds pass ``None``
        and get FastAPI's default no-op lifespan.
    """
    app_kwargs: dict[str, Any] = {
        "title": "agent_server northbound facade",
        "version": AGENT_SERVER_API_VERSION,
    }
    if lifespan is not None:
        app_kwargs["lifespan"] = lifespan
    app = FastAPI(**app_kwargs)
    # Middleware order at request time:
    #   TenantContext (validates X-Tenant-Id) -> Idempotency (consumes ctx)
    # FastAPI's add_middleware inserts at index 0 (last added is OUTERMOST
    # and runs FIRST). To get TenantContext outermost we therefore add the
    # idempotency middleware FIRST and the tenant middleware LAST.
    if idempotency_facade is not None:
        register_idempotency_middleware(
            app, facade=idempotency_facade, strict=idempotency_strict
        )
    if tenant_event_emitter is not None:
        app.add_middleware(
            TenantContextMiddleware, tenant_event_emitter=tenant_event_emitter
        )
    else:
        app.add_middleware(TenantContextMiddleware)

    @app.get("/v1/health")
    async def _health(_request: Request) -> JSONResponse:  # pragma: no cover - smoke
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "api_version": AGENT_SERVER_API_VERSION,
            },
        )

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
        app.include_router(
            _build_skills_memory_router(idempotency_facade=idempotency_facade)
        )
    if include_gates:
        app.include_router(_build_gates_router())
    return app
