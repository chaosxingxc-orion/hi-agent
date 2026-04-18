"""Token-bucket rate limiter middleware for Starlette."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass
class _Bucket:
    """Per-client token bucket."""

    tokens: float
    last_refill: float


# Platform status interfaces are exempt from rate limiting.  These endpoints
# (/ready, /manifest, /mcp/status, /metrics/json) are polled by integrators
# during run lifecycle monitoring and must remain reachable even when business
# API traffic has consumed the per-client token bucket.  /runs/{id} GET is
# NOT listed here — it carries path parameters and is matched by prefix check
# in the middleware.
_EXEMPT_PATHS: frozenset[str] = frozenset({
    "/health",
    "/metrics",
    "/metrics/json",
    "/ready",
    "/manifest",
    "/mcp/status",
})

# Path prefixes whose GET requests are also exempt (e.g. /runs/{id} polling).
_EXEMPT_GET_PREFIXES: tuple[str, ...] = ("/runs/",)

_STALE_SECONDS: float = 600.0  # 10 minutes


class RateLimiter:
    """ASGI middleware implementing per-client-IP token-bucket rate limiting.

    Args:
        app: The wrapped ASGI application.
        max_requests: Maximum tokens (requests) per window.
        window_seconds: Window duration over which *max_requests* tokens
            are fully replenished.
        burst: Initial and maximum bucket size (allows short bursts).
    """

    def __init__(
        self,
        app: ASGIApp,
        max_requests: int = 100,
        window_seconds: float = 60.0,
        burst: int = 20,
    ) -> None:
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.burst = burst
        # Tokens added per second.
        self._rate: float = max_requests / window_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup: float = time.monotonic()

    # ------------------------------------------------------------------
    # ASGI interface
    # ------------------------------------------------------------------

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "")
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        # GET requests to run-status prefixes are exempt so integrators can
        # poll /runs/{id} during a run without exhausting their token bucket.
        if method == "GET" and any(path.startswith(p) for p in _EXEMPT_GET_PREFIXES):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_ip: str = client[0] if client else "unknown"

        # Use tenant-scoped bucket when a TenantContext is present.
        tenant_ctx = scope.get("tenant_context")
        tenant_id: str = tenant_ctx.tenant_id if tenant_ctx is not None else ""

        allowed, retry_after = self._consume(client_ip, tenant_id=tenant_id)
        if not allowed:
            response = JSONResponse(
                {"error": "rate_limit_exceeded"},
                status_code=429,
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    # ------------------------------------------------------------------
    # Token bucket logic (thread-safe)
    # ------------------------------------------------------------------

    def _consume(
        self, client_ip: str, *, tenant_id: str = ""
    ) -> tuple[bool, float]:
        """Try to consume one token for the request bucket.

        When *tenant_id* is non-empty the bucket key is ``tenant:<tenant_id>``;
        otherwise it falls back to ``ip:<client_ip>``.  This keeps all
        existing IP-based behaviour intact when no TenantContext is present.

        Returns:
            ``(allowed, retry_after_seconds)``.
        """
        bucket_key = f"tenant:{tenant_id}" if tenant_id else f"ip:{client_ip}"
        now = time.monotonic()

        with self._lock:
            self._maybe_cleanup(now)

            bucket = self._buckets.get(bucket_key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self.burst), last_refill=now)
                self._buckets[bucket_key] = bucket

            # Refill tokens based on elapsed time.
            elapsed = now - bucket.last_refill
            bucket.tokens = min(
                float(self.burst),
                bucket.tokens + elapsed * self._rate,
            )
            bucket.last_refill = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0

            # How long until one token is available?
            wait = (1.0 - bucket.tokens) / self._rate
            return False, wait

    # ------------------------------------------------------------------
    # Stale bucket cleanup
    # ------------------------------------------------------------------

    def _maybe_cleanup(self, now: float) -> None:
        """Remove buckets not seen for ``_STALE_SECONDS``.

        Must be called while ``self._lock`` is held.
        """
        if now - self._last_cleanup < _STALE_SECONDS:
            return
        self._last_cleanup = now
        self._cleanup_stale_buckets(now)

    def _cleanup_stale_buckets(self, now: float | None = None) -> None:
        """Remove stale buckets.  Safe to call externally with lock held."""
        if now is None:
            now = time.monotonic()
        stale = [
            key
            for key, b in self._buckets.items()
            if now - b.last_refill > _STALE_SECONDS
        ]
        for key in stale:
            del self._buckets[key]
