"""Integration test: POST /runs/{id}/feedback → FeedbackStore row has full spine.

Layer 2 — Integration: real RunManager + real FeedbackStore.
Zero mocks on the subsystem under test.

Asserts that tenant_id, user_id, session_id are all non-empty and match
the auth context after a POST /runs/{run_id}/feedback call.
"""
from __future__ import annotations

import pytest
from hi_agent.evolve.feedback_store import FeedbackStore
from hi_agent.server import routes_runs
from hi_agent.server.run_manager import RunManager
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers (mirror test_run_queue_spine_via_http pattern)
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware:
    """ASGI middleware that injects a fixed TenantContext for each request."""

    def __init__(self, app, ctx: TenantContext) -> None:
        self.app = app
        self._ctx = ctx

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            token = set_tenant_context(self._ctx)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_tenant_context(token)
        else:
            await self.app(scope, receive, send)


class _FakeServer:
    """Minimal AgentServer stand-in used by run route handlers."""

    def __init__(self, manager: RunManager, feedback_store: FeedbackStore) -> None:
        self.run_manager = manager
        self.run_context_manager = None
        self.executor_factory = None
        self.artifact_registry = None
        self._feedback_store = feedback_store


def _build_app(manager: RunManager, feedback_store: FeedbackStore, ctx: TenantContext):
    routes = [
        Route("/runs", routes_runs.handle_create_run, methods=["POST"]),
        Route("/runs/{run_id}", routes_runs.handle_get_run, methods=["GET"]),
        Route(
            "/runs/{run_id}/feedback",
            routes_runs.handle_submit_feedback,
            methods=["POST"],
        ),
        Route(
            "/runs/{run_id}/feedback",
            routes_runs.handle_get_feedback,
            methods=["GET"],
        ),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(manager, feedback_store)
    return _InjectCtxMiddleware(app, ctx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFeedbackStoreSpineViaHttp:
    """POST /runs/{id}/feedback — verify spine fields are stored in FeedbackStore."""

    @pytest.fixture()
    def feedback_store(self, tmp_path):
        return FeedbackStore(storage_path=str(tmp_path / "feedback.json"))

    @pytest.fixture()
    def ctx(self):
        return TenantContext(
            tenant_id="tenant-fb-test",
            user_id="user-fb-test",
            session_id="session-fb-test",
        )

    @pytest.fixture()
    def manager(self):
        rm = RunManager()
        yield rm
        rm.shutdown()

    def _create_run(self, client, project_id: str = "") -> str:
        payload: dict = {"goal": "feedback spine test goal"}
        if project_id:
            payload["project_id"] = project_id
        resp = client.post("/runs", json=payload)
        assert resp.status_code in (200, 201, 202), f"create failed: {resp.text}"
        run_id = resp.json().get("run_id")
        assert run_id
        return run_id

    def test_submit_feedback_populates_spine_fields(self, manager, feedback_store, ctx):
        """POST /runs/{id}/feedback → FeedbackStore record carries tenant_id,
        user_id, session_id from the authenticated TenantContext."""
        app = _build_app(manager, feedback_store, ctx)
        with TestClient(app, raise_server_exceptions=True) as client:
            run_id = self._create_run(client)
            resp = client.post(
                f"/runs/{run_id}/feedback",
                json={"rating": 0.9, "notes": "spine check"},
            )
        assert resp.status_code == 200, f"submit_feedback failed: {resp.text}"

        # Read directly from the FeedbackStore (real component, no mock).
        record = feedback_store.get(run_id)
        assert record is not None, f"no feedback record for run_id={run_id!r}"

        assert record.tenant_id == ctx.tenant_id, (
            f"tenant_id mismatch: got {record.tenant_id!r}, expected {ctx.tenant_id!r}"
        )
        assert record.user_id == ctx.user_id, (
            f"user_id mismatch: got {record.user_id!r}, expected {ctx.user_id!r}"
        )
        assert record.session_id == ctx.session_id, (
            f"session_id mismatch: got {record.session_id!r}, expected {ctx.session_id!r}"
        )

    def test_feedback_rating_and_notes_preserved(self, manager, feedback_store, ctx):
        """Spine fix must not break the core rating/notes storage behaviour."""
        app = _build_app(manager, feedback_store, ctx)
        with TestClient(app, raise_server_exceptions=True) as client:
            run_id = self._create_run(client)
            resp = client.post(
                f"/runs/{run_id}/feedback",
                json={"rating": 0.75, "notes": "accuracy great"},
            )
        assert resp.status_code == 200
        record = feedback_store.get(run_id)
        assert record is not None
        assert record.rating == pytest.approx(0.75)
        assert record.notes == "accuracy great"

    def test_feedback_post_carries_project_id_from_run(
        self, manager, feedback_store, ctx
    ):
        """Spine-3 / P0-4: POST /runs/{id}/feedback must persist the run's
        project_id on the RunFeedback row, derived from the run record (not
        from TenantContext, which does not carry project scope)."""
        app = _build_app(manager, feedback_store, ctx)
        with TestClient(app, raise_server_exceptions=True) as client:
            run_id = self._create_run(client, project_id="proj-X")
            resp = client.post(
                f"/runs/{run_id}/feedback",
                json={"rating": 0.8, "notes": "project scoped feedback"},
            )
        assert resp.status_code == 200, f"submit_feedback failed: {resp.text}"
        record = feedback_store.get(run_id)
        assert record is not None, f"no feedback record for run_id={run_id!r}"
        assert record.project_id == "proj-X", (
            f"project_id mismatch: got {record.project_id!r}, expected 'proj-X'"
        )

    def test_feedback_project_id_empty_when_run_unscoped(
        self, manager, feedback_store, ctx
    ):
        """When the run was created without a project_id, the feedback row
        carries an empty project_id (preserves prior unscoped behaviour for
        legacy callers)."""
        app = _build_app(manager, feedback_store, ctx)
        with TestClient(app, raise_server_exceptions=True) as client:
            run_id = self._create_run(client)  # no project_id
            resp = client.post(
                f"/runs/{run_id}/feedback",
                json={"rating": 0.5, "notes": "no project"},
            )
        assert resp.status_code == 200
        record = feedback_store.get(run_id)
        assert record is not None
        assert record.project_id == ""
