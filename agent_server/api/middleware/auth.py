"""W33-C.4: JWT auth middleware for the agent_server v1 routes.

Per R-AS-1, this module imports JWT validation through the runtime
seam (``agent_server.runtime.auth_seam``) — it MUST NOT import from
``hi_agent.*`` directly. The runtime seam is the only permitted
boundary for cross-package imports under ``agent_server/api/**``.

Behaviour
---------
* Under dev posture the middleware is permissive: a missing or
  malformed Authorization header passes through and downstream
  handlers see ``request.state.auth_claims`` populated with an
  anonymous record.
* Under research/prod posture the middleware is fail-closed: every
  reject reason produces HTTP 401 in the canonical error envelope.

The middleware stores the validated claims on
``request.state.auth_claims`` so the TenantContextMiddleware (which
runs AFTER this middleware in the request flow) can read them when
constructing the tenant context. The middleware order is established
by ``agent_server/api/__init__.py`` — it must add the auth middleware
LAST so Starlette places it OUTERMOST (i.e. runs FIRST).
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from agent_server.runtime.auth_seam import (
    ValidationOutcome,
    validate_authorization,
)

_AUTH_HEADER = "authorization"

# Paths that bypass auth entirely. /v1/health is the smoke probe and
# must remain reachable to operators even when secrets are not yet
# configured.
_EXEMPT_PATHS = frozenset({"/v1/health", "/health", "/metrics"})


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Validate JWT claims (or pass through under dev posture)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        audience: str = "hi-agent",
    ) -> None:
        super().__init__(app)
        self._audience = audience

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get(_AUTH_HEADER, "")
        outcome: ValidationOutcome = validate_authorization(
            auth_header, audience=self._audience
        )
        if not outcome.ok:
            return JSONResponse(
                status_code=outcome.status,
                content={
                    "error_category": "auth",
                    "message": "unauthorized",
                    "reason": outcome.reason,
                    "retryable": False,
                    "next_action": (
                        "Supply a valid Bearer JWT in the Authorization header. "
                        "Under research/prod posture a JWT signed with "
                        "HI_AGENT_JWT_SECRET is required."
                    ),
                },
                headers={"WWW-Authenticate": 'Bearer realm="agent-server"'},
            )
        request.state.auth_claims = dict(outcome.claims)
        return await call_next(request)


__all__ = ["JWTAuthMiddleware"]
