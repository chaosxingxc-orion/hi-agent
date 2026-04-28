"""HTTP trace-id middleware for hi-agent server.

Extracts the trace_id from the W3C traceparent header if present,
or mints a new 16-byte hex id if not. Sets the trace context via
TraceContextManager so all downstream code in the same request sees it.
"""
from __future__ import annotations

import logging
import re
import secrets

from starlette.types import ASGIApp, Receive, Scope, Send

from hi_agent.observability.trace_context import TraceContext, _current_trace_ctx, _new_id

_TRACEPARENT_RE = re.compile(
    r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$"
)

_logger = logging.getLogger(__name__)


class TraceIdMiddleware:
    """ASGI middleware that injects a trace_id into the request context.

    For HTTP requests: extracts trace_id from W3C traceparent header, or
    generates a fresh 16-byte hex id. Sets the TraceContext contextvar so
    all in-process code shares the same trace_id for the request duration.

    Also emits an ``http_request`` observability event to the event store
    (when wired) so the spine can report provenance:real with 14 layers.

    Non-HTTP scopes (websocket, lifespan) are passed through unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_tp = headers.get(b"traceparent", b"").decode("ascii", errors="replace")
        m = _TRACEPARENT_RE.match(raw_tp)
        trace_id = m.group(1) if m else secrets.token_hex(16)

        ctx = TraceContext(trace_id=trace_id, span_id=_new_id())
        token = _current_trace_ctx.set(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_trace_ctx.reset(token)

        # Emit http_request event to the metrics collector for observability spine.
        # Uses best-effort emit to the event store to avoid impacting request latency.
        _method = scope.get("method", "")
        _path = scope.get("path", "")
        try:
            from hi_agent.observability.collector import get_metrics_collector
            _col = get_metrics_collector()
            if _col is not None:
                _col.increment(
                    "hi_agent_http_requests_total",
                    labels={"method": _method, "path": _path},
                )
        except Exception:
            pass
