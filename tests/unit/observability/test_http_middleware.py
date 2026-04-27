"""Unit tests for TraceIdMiddleware."""
from __future__ import annotations

from hi_agent.observability.http_middleware import TraceIdMiddleware
from hi_agent.observability.trace_context import TraceContextManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _make_app() -> Starlette:
    mgr = TraceContextManager()

    async def homepage(request):
        ctx = mgr.current()
        return JSONResponse({"trace_id": ctx.trace_id if ctx else None})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(TraceIdMiddleware)
    return app


def test_extracts_trace_id_from_traceparent():
    app = _make_app()
    client = TestClient(app)
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    resp = client.get("/", headers={"traceparent": tp})
    assert resp.status_code == 200
    assert resp.json()["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_generates_trace_id_when_no_header():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    tid = resp.json()["trace_id"]
    assert tid is not None
    assert len(tid) == 32  # 16 bytes hex


def test_different_requests_get_different_trace_ids():
    app = _make_app()
    client = TestClient(app)
    t1 = client.get("/").json()["trace_id"]
    t2 = client.get("/").json()["trace_id"]
    assert t1 != t2
