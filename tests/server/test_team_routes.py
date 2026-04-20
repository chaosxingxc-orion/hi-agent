"""Acceptance tests 16-18: /team/events route via TeamEventStore.

Test 16: publish one event as user u1; user u2 in same team (team_id="eng") sees it.
Test 17: nothing published → GET /team/events returns empty list.
Test 18: 20 concurrent publishes → all 20 persisted and visible.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from hi_agent.server.routes_team import handle_list_team_events
from hi_agent.server.team_event_store import TeamEvent, TeamEventStore
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext for every request (bypasses AuthMiddleware)."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request, call_next):
        request.scope["tenant_context"] = self._ctx
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _FakeServer:
    """Minimal AgentServer stand-in for route handlers."""

    def __init__(self, store: TeamEventStore) -> None:
        self.team_event_store = store


def _build_app(store: TeamEventStore, ctx: TenantContext) -> Starlette:
    """Build a minimal Starlette app with the /team/events route and injected context."""
    fake_server = _FakeServer(store)
    routes = [
        Route("/team/events", handle_list_team_events, methods=["GET"]),
    ]
    inner = Starlette(routes=routes)
    inner.state.agent_server = fake_server

    class _Wrapper(BaseHTTPMiddleware):
        def __init__(self, app, ctx: TenantContext) -> None:
            super().__init__(app)
            self._ctx = ctx

        async def dispatch(self, request, call_next):
            request.scope["tenant_context"] = self._ctx
            token = set_tenant_context(self._ctx)
            try:
                return await call_next(request)
            finally:
                reset_tenant_context(token)

    inner.add_middleware(_Wrapper, ctx=ctx)
    return inner


def _make_event(tenant_id: str, team_id: str, user_id: str) -> TeamEvent:
    return TeamEvent(
        event_id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        team_space_id=team_id,
        event_type="run.completed",
        payload_json='{"result": "ok"}',
        source_run_id="run-001",
        source_user_id=user_id,
        source_session_id="",
        publish_reason="test",
        schema_version=1,
        created_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Test 16: u1 publishes event; u2 in same team can see it
# ---------------------------------------------------------------------------


def test_16_cross_user_same_team_visibility():
    """User u2 in the same team should see an event published by user u1."""
    store = TeamEventStore(db_path=":memory:")
    store.initialize()

    tenant_id = "tenant-acme"
    team_id = "eng"

    # u1 publishes one event
    event = _make_event(tenant_id, team_id, user_id="u1")
    store.insert(event)

    # u2 queries /team/events — same tenant, same team_id
    ctx_u2 = TenantContext(
        tenant_id=tenant_id,
        team_id=team_id,
        user_id="u2",
    )
    app = _build_app(store, ctx_u2)

    with TestClient(app) as client:
        resp = client.get("/team/events")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "events" in body
    assert len(body["events"]) == 1
    assert body["events"][0]["source_user_id"] == "u1"
    assert body["events"][0]["event_type"] == "run.completed"


# ---------------------------------------------------------------------------
# Test 17: nothing published → empty list
# ---------------------------------------------------------------------------


def test_17_empty_list_when_no_events():
    """GET /team/events returns an empty list when no events have been published."""
    store = TeamEventStore(db_path=":memory:")
    store.initialize()

    ctx = TenantContext(
        tenant_id="tenant-empty",
        team_id="backend",
        user_id="u1",
    )
    app = _build_app(store, ctx)

    with TestClient(app) as client:
        resp = client.get("/team/events")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"events": []}


# ---------------------------------------------------------------------------
# Test 18: 20 concurrent publishes → all 20 persisted
# ---------------------------------------------------------------------------


def test_18_concurrent_publishes_all_persisted():
    """20 concurrent inserts must all be persisted and visible via GET /team/events."""
    store = TeamEventStore(db_path=":memory:")
    store.initialize()

    tenant_id = "tenant-concurrent"
    team_id = "ops"
    n = 20

    def _publish(i: int) -> None:
        ev = TeamEvent(
            event_id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            team_space_id=team_id,
            event_type=f"run.step.{i}",
            payload_json=f'{{"step": {i}}}',
            source_run_id=f"run-{i:03d}",
            source_user_id=f"u{i}",
            source_session_id="",
            publish_reason="load-test",
            schema_version=1,
            created_at=time.time(),
        )
        store.insert(ev)

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(_publish, range(n)))

    # Verify all 20 are in the store
    events = store.list_since(tenant_id, team_id, since_id=0)
    assert len(events) == n, f"Expected {n} events, got {len(events)}"

    # Also verify via the HTTP route
    ctx = TenantContext(
        tenant_id=tenant_id,
        team_id=team_id,
        user_id="observer",
    )
    app = _build_app(store, ctx)

    with TestClient(app) as client:
        resp = client.get("/team/events")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["events"]) == n, f"HTTP saw {len(body['events'])} instead of {n}"
