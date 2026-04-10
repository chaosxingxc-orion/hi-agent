"""Tests for RateLimiter ASGI middleware."""

from __future__ import annotations

import pytest

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hi_agent.server.rate_limiter import RateLimiter


def _make_app(max_requests: int = 5, window_seconds: float = 60.0, burst: int = 3):
    async def home(request):
        return JSONResponse({"ok": True})

    async def health(request):
        return JSONResponse({"status": "healthy"})

    async def metrics(request):
        return JSONResponse({"metrics": []})

    app = Starlette(
        routes=[
            Route("/", home),
            Route("/health", health),
            Route("/metrics", metrics),
            Route("/api/test", home),
        ]
    )
    return RateLimiter(
        app, max_requests=max_requests, window_seconds=window_seconds, burst=burst
    )


class TestRateLimiter:
    """RateLimiter tests."""

    def test_under_limit_passes(self):
        app = _make_app(max_requests=100, burst=10)
        client = TestClient(app)
        resp = client.get("/api/test")
        assert resp.status_code == 200

    def test_over_limit_429(self):
        app = _make_app(max_requests=1, window_seconds=60.0, burst=2)
        client = TestClient(app)
        # Burst allows 2, then 3rd should fail
        client.get("/api/test")
        client.get("/api/test")
        resp = client.get("/api/test")
        assert resp.status_code == 429
        assert "rate_limit_exceeded" in resp.json()["error"]

    def test_health_exempt(self):
        app = _make_app(max_requests=1, burst=1)
        client = TestClient(app)
        # Exhaust the limit
        client.get("/api/test")
        client.get("/api/test")
        # /health should still pass
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_metrics_exempt(self):
        app = _make_app(max_requests=1, burst=1)
        client = TestClient(app)
        client.get("/api/test")
        client.get("/api/test")
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_token_refill(self):
        """Tokens should refill over time (we test via high rate)."""
        # With very high rate, tokens refill almost instantly
        app = _make_app(max_requests=10000, window_seconds=1.0, burst=2)
        client = TestClient(app)
        # Use up burst
        client.get("/api/test")
        client.get("/api/test")
        # High refill rate means next request should also pass
        resp = client.get("/api/test")
        assert resp.status_code == 200

    def test_stale_cleanup(self):
        """Verify stale bucket cleanup does not crash."""
        from hi_agent.server.rate_limiter import RateLimiter as RL

        async def noop(scope, receive, send):
            pass

        limiter = RL(noop, max_requests=10, burst=10)
        # Simulate a consume to create a bucket
        allowed, _ = limiter._consume("1.2.3.4")
        assert allowed
        # Call cleanup directly
        import time
        limiter._cleanup_stale_buckets(time.monotonic() + 99999)
        # Bucket should have been cleaned
        assert "1.2.3.4" not in limiter._buckets
