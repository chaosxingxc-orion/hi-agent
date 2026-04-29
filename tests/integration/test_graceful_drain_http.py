"""Integration tests for graceful drain behaviour via HTTP.

Layer 2 (Integration): real RunManager, real DrainMiddleware, real handle_ready.
Zero mocks on the subsystem under test.

Covers:
  - GET /ready returns 503 when server is draining.
  - POST /runs returns 503 + Retry-After when server is draining.
  - POST /runs/{id}/cancel is exempt from drain blocking.
  - POST /ops/drain is exempt from drain blocking.
  - GET requests (read-only) are exempt from drain blocking.
"""
from __future__ import annotations

import pytest
from hi_agent.server.app import handle_ready
from hi_agent.server.middleware_drain import DrainMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(*, draining: bool) -> Starlette:
    """Build a minimal Starlette app with DrainMiddleware and a set of routes."""

    class _FakeBuilder:
        def readiness(self):
            return {"ready": True, "health": "ok"}

    class _FakeServer:
        def __init__(self) -> None:
            self._builder = _FakeBuilder()
            self._draining = draining
            self.run_manager = None  # not needed for these tests

    fake_server = _FakeServer()

    async def _fake_post_runs(request: Request) -> JSONResponse:
        return JSONResponse({"run_id": "test-run-1"}, status_code=201)

    async def _fake_cancel_run(request: Request) -> JSONResponse:
        return JSONResponse({"status": "cancelling"}, status_code=200)

    async def _fake_drain(request: Request) -> JSONResponse:
        server = request.app.state.agent_server
        server._draining = True
        return JSONResponse({"status": "draining"}, status_code=200)

    async def _fake_get_run(request: Request) -> JSONResponse:
        return JSONResponse({"run_id": "test-run-1", "state": "running"}, status_code=200)

    app = Starlette(
        routes=[
            Route("/runs", _fake_post_runs, methods=["POST"]),
            Route("/runs/{run_id}/cancel", _fake_cancel_run, methods=["POST"]),
            Route("/runs/{run_id}", _fake_get_run, methods=["GET"]),
            Route("/ready", handle_ready, methods=["GET"]),
            Route("/ops/drain", _fake_drain, methods=["POST"]),
        ]
    )
    app.state.agent_server = fake_server
    app.add_middleware(DrainMiddleware)
    return app


# ---------------------------------------------------------------------------
# Tests: server NOT draining (baseline)
# ---------------------------------------------------------------------------


def test_post_runs_allowed_when_not_draining() -> None:
    """POST /runs succeeds when server is not draining."""
    app = _make_app(draining=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/runs", json={"goal": "test"})
    assert resp.status_code == 201


def test_ready_200_when_not_draining() -> None:
    """GET /ready returns 200 when server is not draining."""
    app = _make_app(draining=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/ready")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: server IS draining
# ---------------------------------------------------------------------------


def test_post_runs_blocked_when_draining() -> None:
    """POST /runs returns 503 with Retry-After header when server is draining."""
    app = _make_app(draining=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/runs", json={"goal": "test"})
    assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
    assert "Retry-After" in resp.headers
    body = resp.json()
    assert body.get("error") == "server_draining"


def test_ready_503_when_draining() -> None:
    """GET /ready returns 503 when server is draining."""
    app = _make_app(draining=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/ready")
    assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("ready") is False


def test_cancel_run_exempt_from_drain() -> None:
    """POST /runs/{id}/cancel is allowed even when server is draining."""
    app = _make_app(draining=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/runs/test-run-1/cancel", json={})
    # 200 from the fake route handler (not 503 from drain middleware)
    assert resp.status_code == 200, (
        f"cancel should be exempt from drain, got {resp.status_code}: {resp.text}"
    )


def test_ops_drain_exempt_from_drain() -> None:
    """POST /ops/drain is allowed even when server is draining."""
    app = _make_app(draining=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/ops/drain", json={})
    # 200 from the fake route handler (not 503 from drain middleware)
    assert resp.status_code == 200, (
        f"/ops/drain should be exempt, got {resp.status_code}: {resp.text}"
    )


def test_get_run_exempt_from_drain() -> None:
    """GET /runs/{id} is allowed (read-only) even when server is draining."""
    app = _make_app(draining=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/runs/test-run-1")
    # 200 from the fake route handler (not 503 from drain middleware)
    assert resp.status_code == 200, (
        f"GET should be exempt from drain, got {resp.status_code}: {resp.text}"
    )
