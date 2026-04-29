"""Drain middleware: rejects mutating requests when server is draining.

When the server is in draining mode (``AgentServer._draining == True``),
POST/PUT/DELETE requests to data-mutation endpoints return HTTP 503 with a
``Retry-After: 30`` header and a JSON ``{"error": "server_draining"}`` body.

Exempted from drain blocking:
  - All GET / HEAD / OPTIONS requests (read-only).
  - ``POST /ops/drain``      — the drain-trigger itself must pass through.
  - ``POST /runs/{id}/cancel`` — operators must be able to cancel in-flight runs.
  - ``POST /runs/{id}/signal`` — operators must be able to signal runs.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Paths that are always allowed even during drain.
_DRAIN_EXEMPT_PREFIXES = (
    "/ops/drain",
)
_DRAIN_EXEMPT_SUFFIXES = (
    "/cancel",
    "/signal",
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class DrainMiddleware(BaseHTTPMiddleware):
    """Reject mutating requests with 503 when server is draining.

    The middleware reads ``request.app.state.agent_server._draining``.
    If that attribute is absent or False the middleware is a no-op.
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]  # expiry_wave: Wave 21
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        path = request.url.path

        # Exempt drain-control and cancel/signal endpoints.
        for prefix in _DRAIN_EXEMPT_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                return await call_next(request)
        for suffix in _DRAIN_EXEMPT_SUFFIXES:
            if path.endswith(suffix):
                return await call_next(request)

        # Check draining state from the agent server.
        try:
            server = request.app.state.agent_server
            is_draining: bool = getattr(server, "_draining", False)
        except AttributeError:
            is_draining = False

        if is_draining:
            return JSONResponse(
                {"error": "server_draining"},
                status_code=503,
                headers={"Retry-After": "30"},
            )

        return await call_next(request)
