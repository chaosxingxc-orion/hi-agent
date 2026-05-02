"""Tenant-context middleware (R-AS-4).

Reads the X-Tenant-Id header (required) and attaches a TenantContext
instance to ``request.state.tenant_context`` for downstream handlers.

Handlers MUST read the tenant from request state, never from the request
body, per R-AS-4. A missing or empty header yields 401 Unauthorized so
the platform fails closed under research/prod posture.

HD-5 (W24-J5): the 401 response uses the unified error envelope shape
``{error_category, message, retryable, next_action}`` so callers can
parse auth errors without string-matching.

W31-N (N.4): the tenant-context spine emitter is injected via a
constructor argument. The bootstrap module is the single seam allowed
to bind it to ``hi_agent.observability.spine_events.emit_tenant_context``
(R-AS-1). Tests and modules that build the app directly receive the
no-op default and never reach hi_agent.
"""
from __future__ import annotations

from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from agent_server.contracts.errors import AuthError
from agent_server.contracts.tenancy import TenantContext

TENANT_HEADER = "X-Tenant-Id"
PROJECT_HEADER = "X-Project-Id"
PROFILE_HEADER = "X-Profile-Id"
SESSION_HEADER = "X-Session-Id"

TenantEventEmitter = Callable[[str], None]


def _noop_emitter(_tenant_id: str) -> None:
    """Default tenant-context emitter that does nothing.

    Used when no observability emitter is wired (route-level unit tests,
    the default-offline profile). Replaced by the bootstrap with the
    real ``hi_agent.observability.spine_events.emit_tenant_context``.
    """
    return None


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Inject a TenantContext into request state from request headers."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        tenant_event_emitter: TenantEventEmitter = _noop_emitter,
    ) -> None:
        super().__init__(app)
        self._tenant_event_emitter = tenant_event_emitter

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]  # expiry_wave: permanent
        tenant_id = request.headers.get(TENANT_HEADER, "").strip()
        if not tenant_id:
            err = AuthError(f"missing or empty {TENANT_HEADER} header")
            return JSONResponse(status_code=err.http_status, content=err.to_envelope())
        request.state.tenant_context = TenantContext(
            tenant_id=tenant_id,
            project_id=request.headers.get(PROJECT_HEADER, "").strip(),
            profile_id=request.headers.get(PROFILE_HEADER, "").strip(),
            session_id=request.headers.get(SESSION_HEADER, "").strip(),
        )
        # w25-F: spine tap for tenant_context layer (W31-N N.4: emitter
        # is injected — bootstrap binds the real spine; default no-op).
        self._tenant_event_emitter(tenant_id)
        return await call_next(request)
