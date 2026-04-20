"""Tests for RateLimiter ASGI middleware."""

from __future__ import annotations

from hi_agent.server.rate_limiter import RateLimiter
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _make_app(max_requests: int = 5, window_seconds: float = 60.0, burst: int = 3):
    async def home(request):
        return JSONResponse({"ok": True})

    async def health(request):
        return JSONResponse({"status": "healthy"})

    async def metrics(request):
        return JSONResponse({"metrics": []})

    async def ready(request):
        return JSONResponse({"ready": True})

    async def manifest(request):
        return JSONResponse({"version": "1"})

    async def mcp_status(request):
        return JSONResponse({"status": "ok"})

    async def metrics_json(request):
        return JSONResponse({"metrics": {}})

    async def run_detail(request):
        return JSONResponse({"run_id": request.path_params["run_id"]})

    app = Starlette(
        routes=[
            Route("/", home),
            Route("/health", health),
            Route("/metrics", metrics),
            Route("/metrics/json", metrics_json),
            Route("/ready", ready),
            Route("/manifest", manifest),
            Route("/mcp/status", mcp_status),
            Route("/runs/{run_id}", run_detail),
            Route("/api/test", home),
        ]
    )
    return RateLimiter(app, max_requests=max_requests, window_seconds=window_seconds, burst=burst)


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

    def test_ready_exempt(self):
        """GET /ready must be exempt — platform readiness check must survive exhausted bucket."""
        app = _make_app(max_requests=1, burst=1)
        client = TestClient(app)
        # Exhaust the bucket on a normal endpoint.
        client.get("/api/test")
        client.get("/api/test")
        resp = client.get("/ready")
        assert resp.status_code == 200

    def test_manifest_exempt(self):
        """GET /manifest must be exempt — integrators poll this during onboarding."""
        app = _make_app(max_requests=1, burst=1)
        client = TestClient(app)
        client.get("/api/test")
        client.get("/api/test")
        resp = client.get("/manifest")
        assert resp.status_code == 200

    def test_mcp_status_exempt(self):
        """GET /mcp/status must be exempt — MCP capability check must not be throttled."""
        app = _make_app(max_requests=1, burst=1)
        client = TestClient(app)
        client.get("/api/test")
        client.get("/api/test")
        resp = client.get("/mcp/status")
        assert resp.status_code == 200

    def test_metrics_json_exempt(self):
        """GET /metrics/json must be exempt along with /metrics."""
        app = _make_app(max_requests=1, burst=1)
        client = TestClient(app)
        client.get("/api/test")
        client.get("/api/test")
        resp = client.get("/metrics/json")
        assert resp.status_code == 200

    def test_runs_detail_get_exempt(self):
        """GET /runs/{id} must be exempt — run polling must survive exhausted bucket."""
        app = _make_app(max_requests=1, burst=1)
        client = TestClient(app)
        # Exhaust the bucket.
        client.get("/api/test")
        client.get("/api/test")
        resp = client.get("/runs/run-abc123")
        assert resp.status_code == 200

    def test_status_endpoints_reachable_during_burst(self):
        """All platform status endpoints return 200 even when business burst is exhausted.

        This test replicates the downstream P0 scenario:
        > POST /runs → poll GET /runs/{id} → then access /ready, /manifest, /mcp/status
        > After 20+ requests, /ready and /mcp/status were returning 429.
        """
        app = _make_app(max_requests=5, burst=3)
        client = TestClient(app)
        # Exhaust burst on API endpoint.
        for _ in range(5):
            client.get("/api/test")
        # All platform status interfaces must still respond.
        for path in ["/ready", "/manifest", "/mcp/status", "/health", "/metrics/json"]:
            resp = client.get(path)
            assert resp.status_code == 200, (
                f"{path} returned {resp.status_code} after burst exhaustion — "
                "platform status contract violated"
            )
        # Run GET polling must also still work.
        resp = client.get("/runs/run-deadbeef")
        assert resp.status_code == 200, (
            f"/runs/{{id}} GET returned {resp.status_code} after burst exhaustion"
        )

    def test_stale_cleanup(self):
        """Verify stale bucket cleanup does not crash."""
        from hi_agent.server.rate_limiter import RateLimiter

        async def noop(scope, receive, send):
            pass

        limiter = RateLimiter(noop, max_requests=10, burst=10)
        # Simulate a consume to create a bucket
        allowed, _ = limiter._consume("1.2.3.4")
        assert allowed
        # Call cleanup directly
        import time

        limiter._cleanup_stale_buckets(time.monotonic() + 99999)
        # Bucket should have been cleaned
        assert "1.2.3.4" not in limiter._buckets
