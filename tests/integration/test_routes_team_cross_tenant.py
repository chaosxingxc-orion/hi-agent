"""Cross-tenant isolation integration tests for team event routes (W5-G).

Verifies that Tenant B cannot see Tenant A's team events.

Layer 2 — Integration: real TeamEventStore + real route handlers.
No MagicMock on the subsystem under test.
"""
from __future__ import annotations

import time
import uuid

import pytest
from hi_agent.server import routes_team
from hi_agent.server.team_event_store import TeamEvent, TeamEventStore
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext per request (bypasses AuthMiddleware)."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request: Request, call_next):
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _FakeServer:
    """Minimal stand-in for AgentServer used by team route handlers."""

    def __init__(self, store: TeamEventStore) -> None:
        self.team_event_store = store


def _build_app(store: TeamEventStore, ctx: TenantContext) -> Starlette:
    """Build a minimal ASGI app with /team/events route and injected TenantContext."""
    app_routes = [
        Route("/team/events", routes_team.handle_list_team_events, methods=["GET"]),
    ]
    app = Starlette(routes=app_routes)
    app.state.agent_server = _FakeServer(store)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _make_event(tenant_id: str, team_space_id: str) -> TeamEvent:
    return TeamEvent(
        event_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        team_space_id=team_space_id,
        event_type="test.event",
        payload_json="{}",
        source_run_id="",
        source_user_id="",
        source_session_id="",
        publish_reason="test",
        schema_version=1,
        created_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrossTenantTeamEventIsolation:
    """GET /team/events — Tenant B cannot see Tenant A's events."""

    @pytest.fixture()
    def store(self):
        s = TeamEventStore(db_path=":memory:")
        s.initialize()
        return s

    @pytest.fixture()
    def event_a(self, store) -> TeamEvent:
        evt = _make_event(tenant_id="tenant-A", team_space_id="tenant-A")
        store.insert(evt)
        return evt

    def test_tenant_b_cannot_see_tenant_a_events(self, store, event_a):
        """GET /team/events for Tenant B must not return Tenant A's events."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")
        app = _build_app(store, ctx_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/team/events")
        assert resp.status_code == 200
        event_ids = [e.get("event_id") for e in resp.json().get("events", [])]
        assert event_a.event_id not in event_ids, (
            f"Tenant B's event list leaked Tenant A's event_id={event_a.event_id}"
        )

    def test_tenant_a_can_see_own_events(self, store, event_a):
        """GET /team/events for Tenant A returns its own events."""
        ctx_a = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
        app = _build_app(store, ctx_a)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/team/events")
        assert resp.status_code == 200
        event_ids = [e.get("event_id") for e in resp.json().get("events", [])]
        assert event_a.event_id in event_ids, (
            f"Tenant A's own event_id={event_a.event_id} not returned in list"
        )

    def test_tenant_b_empty_list_not_tenant_a_data(self, store, event_a):
        """Tenant B receives empty list, not Tenant A's events (no data leak)."""
        ctx_b = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")
        app = _build_app(store, ctx_b)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/team/events")
        assert resp.status_code == 200
        events = resp.json().get("events", [])
        assert events == [], f"Expected empty list for Tenant B, got: {events}"
