"""agent_server.api — northbound HTTP surface (W23 Phase 1)."""
from __future__ import annotations

from fastapi import FastAPI

from agent_server import AGENT_SERVER_API_VERSION
from agent_server.api.middleware.tenant_context import TenantContextMiddleware
from agent_server.api.routes_runs import build_router as _build_runs_router
from agent_server.facade.run_facade import RunFacade

__all__ = ["build_app"]


def build_app(*, run_facade: RunFacade) -> FastAPI:
    """Construct the agent_server ASGI app with routes + middleware wired.

    Parameters
    ----------
    run_facade:
        Pre-constructed :class:`RunFacade` whose injected callables bind
        to the kernel (real or stub). Routes never see the kernel
        directly — they only ever talk to the facade.
    """
    app = FastAPI(
        title="agent_server northbound facade",
        version=AGENT_SERVER_API_VERSION,
    )
    app.add_middleware(TenantContextMiddleware)
    app.include_router(_build_runs_router(run_facade=run_facade))
    return app
