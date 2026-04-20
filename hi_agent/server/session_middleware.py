"""ASGI middleware that validates/auto-creates sessions.

Route-aware rules:
- POST /runs → auto-create session if X-Session-Id header absent
- GET /runs → absent header is OK (optional)
- GET /runs/{id} and other specific run routes → session optional
- /health, /ready, /metrics, /manifest → bypass entirely
- All other workspace routes → require valid X-Session-Id
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from hi_agent.server.session_store import SessionStore
from hi_agent.server.tenant_context import get_tenant_context

# Paths where session middleware is completely bypassed
_EXEMPT_PATHS = frozenset({"/health", "/ready", "/metrics", "/metrics/json", "/manifest"})

# (method, path) pairs where absent X-Session-Id triggers auto-creation
_SESSION_AUTOCREATE = frozenset({("POST", "/runs")})

# Path prefixes where absent X-Session-Id is silently OK (no error, no creation)
_SESSION_OPTIONAL_PREFIXES = ("/runs",)  # covers GET /runs and GET /runs/{id}


class SessionMiddleware:
    """ASGI middleware that validates/auto-creates sessions based on routes."""

    def __init__(self, app: ASGIApp, session_store: SessionStore) -> None:
        """Initialize middleware.

        Args:
            app: Next ASGI application in the stack.
            session_store: SessionStore instance for session operations.
        """
        self._app = app
        self._store = session_store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        method = request.method

        # Bypass for operational / exempt routes
        if path in _EXEMPT_PATHS:
            await self._app(scope, receive, send)
            return

        ctx = scope.get("tenant_context") or get_tenant_context()
        if ctx is None:
            # Auth hasn't set context yet — pass through (auth will reject)
            await self._app(scope, receive, send)
            return

        header_sid = request.headers.get("X-Session-Id", "").strip()
        new_session_id: str | None = None

        if header_sid:
            # Validate ownership
            if not self._store.validate_ownership(
                header_sid, ctx.tenant_id, ctx.user_id
            ):
                resp = JSONResponse(
                    {"error": "session not found or access denied"}, status_code=403
                )
                await resp(scope, receive, send)
                return
            ctx.session_id = header_sid

        elif (method, path) in _SESSION_AUTOCREATE:
            # Auto-create session for POST /runs
            new_session_id = self._store.create(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                team_id=ctx.team_id,
            )
            ctx.session_id = new_session_id

        elif method == "GET" and any(
            path == p or path.startswith(p + "/") for p in _SESSION_OPTIONAL_PREFIXES
        ):
            # GET /runs and GET /runs/{id} — session optional
            pass

        else:
            # All other workspace routes require a valid session
            resp = JSONResponse(
                {"error": "X-Session-Id header required"}, status_code=400
            )
            await resp(scope, receive, send)
            return

        # Propagate updated context into scope
        scope["tenant_context"] = ctx

        if new_session_id:
            # Inject X-Session-Id into response headers
            async def send_with_header(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-session-id", new_session_id.encode()))
                    await send({**message, "headers": headers})
                else:
                    await send(message)

            await self._app(scope, receive, send_with_header)
        else:
            await self._app(scope, receive, send)
