"""Tenant-context middleware (R-AS-4).

Reads the X-Tenant-Id header (required) and attaches a TenantContext
instance to ``request.state.tenant_context`` for downstream handlers.

Handlers MUST read the tenant from request state, never from the request
body, per R-AS-4. A missing or empty header yields 401 Unauthorized so
the platform fails closed under research/prod posture.

HD-5 (W24-J5): the 401 response uses the unified error envelope shape
``{error_category, message, retryable, next_action}`` so callers can
parse auth errors without string-matching.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_server.contracts.errors import AuthError
from agent_server.contracts.tenancy import TenantContext

TENANT_HEADER = "X-Tenant-Id"
PROJECT_HEADER = "X-Project-Id"
PROFILE_HEADER = "X-Profile-Id"
SESSION_HEADER = "X-Session-Id"


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Inject a TenantContext into request state from request headers."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]  # expiry_wave: Wave 28
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
        # w25-F: spine tap for tenant_context layer
        try:
            from hi_agent.observability.spine_events import emit_tenant_context
            emit_tenant_context(tenant_id=tenant_id)
        except Exception:  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 28
            pass
        return await call_next(request)
