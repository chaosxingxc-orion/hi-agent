"""Cross-tenant object-level access denial tests — extended (Track W2-B, Wave 10.2).

Audit-driven sibling to ``test_cross_tenant_object_level.py``.  The Wave 10.1
closure notice acknowledged that a small backlog of routes had handler-level
tenant scope but lacked explicit cross-tenant denial tests.  Without tests,
refactors could silently regress the filter.

Routes covered here (handlers already enforce scope; tests pin behaviour):
  - GET  /runs/active                          -- runs_active list
  - POST /runs/{run_id}/resume                 -- checkpoint resume
  - POST /replay/{run_id}                      -- replay trigger
  - GET  /replay/{run_id}/status               -- replay status
  - GET  /long-ops/{op_id}                     -- long-running op handle
  - POST /long-ops/{op_id}/cancel              -- long-running op cancel
  - GET  /sessions                             -- list sessions
  - GET  /sessions/{session_id}/runs           -- session runs
  - PATCH /sessions/{session_id}               -- archive session
  - GET  /team/events?team_space_id=...        -- team events
  - GET  /artifacts                            -- list artifacts
  - GET  /artifacts/{id}/provenance            -- artifact provenance

Pattern mirrors ``test_cross_tenant_object_level.py``: real subsystems wired
together, no MagicMock on the unit under test, and ``_InjectCtxMiddleware``
to bypass AuthMiddleware while propagating a real ``TenantContext``.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from hi_agent.server import routes_runs
from hi_agent.server.routes_artifacts import artifact_routes
from hi_agent.server.run_manager import RunManager
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
# Shared helpers (mirror test_cross_tenant_object_level.py)
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext per request (bypasses AuthMiddleware)."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request: Request, call_next):
        request.scope["tenant_context"] = self._ctx
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


class _FakeServer:
    """Minimal stand-in for AgentServer used by route handlers."""

    def __init__(self, manager: RunManager) -> None:
        self.run_manager = manager
        self.run_context_manager = None
        self.executor_factory = None
        self.artifact_registry = None
        self._feedback_store = None
        self.op_coordinator = None
        self.session_store = None
        self.team_event_store = None
        # Builder is required by /runs/{id}/resume's background thread.  Tests
        # never reach the background thread because they use a foreign tenant
        # which short-circuits at the ownership check, but the attribute must
        # exist to avoid AttributeError on alternative paths.
        self._builder = None


@pytest.fixture()
def manager():
    rm = RunManager()
    yield rm
    rm.shutdown()


CTX_A = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
CTX_B = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")


def _build_app(routes: list[Route], ctx: TenantContext, manager: RunManager) -> Starlette:
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(manager)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _create_run(manager: RunManager, ctx: TenantContext, *, goal: str = "test") -> str:
    """Create a run directly through RunManager bound to ``ctx``.

    Returns the new run_id.
    """
    body = {"goal": goal}
    managed = manager.create_run(body, workspace=ctx)
    return managed.run_id


# ---------------------------------------------------------------------------
# 1. /runs/active — list filtering
# ---------------------------------------------------------------------------


class TestCrossTenantRunsActive:
    """GET /runs/active — Tenant B does not see Tenant A's active runs."""

    def test_tenant_b_cannot_see_tenant_a_active_run(self, manager):
        # Tenant A creates a run and it is registered as active via RCM.
        run_id_a = _create_run(manager, CTX_A, goal="A-active")

        from hi_agent.context.run_context import RunContextManager

        rcm = RunContextManager()
        rcm.get_or_create(run_id_a)

        routes = [Route("/runs/active", routes_runs.handle_runs_active, methods=["GET"])]

        # Tenant A: confirms the run is in their active list.
        app_a = _build_app(routes, CTX_A, manager)
        app_a.state.agent_server.run_context_manager = rcm
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            resp_a = ca.get("/runs/active")
            assert resp_a.status_code == 200, resp_a.text
            assert run_id_a in resp_a.json().get("run_ids", [])

        # Tenant B: must not see Tenant A's run id.
        app_b = _build_app(routes, CTX_B, manager)
        app_b.state.agent_server.run_context_manager = rcm
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp_b = cb.get("/runs/active")
            assert resp_b.status_code == 200, resp_b.text
            ids = resp_b.json().get("run_ids", [])
            assert run_id_a not in ids, (
                f"Tenant B leaked Tenant A's run_id {run_id_a}: {ids}"
            )


# ---------------------------------------------------------------------------
# 2. /runs/{run_id}/resume — checkpoint resume
# ---------------------------------------------------------------------------


class TestCrossTenantResumeRun:
    """POST /runs/{run_id}/resume — Tenant B cannot resume Tenant A's run."""

    def test_tenant_b_cannot_resume_tenant_a_run(self, manager, tmp_path, monkeypatch):
        # Tenant A creates a run and stages a checkpoint file on disk.
        run_id_a = _create_run(manager, CTX_A, goal="A-resume")
        # Run inside tmp_path so the candidate-path check finds the file
        # without polluting the repo.
        monkeypatch.chdir(tmp_path)
        ckpt_dir = tmp_path / ".checkpoint"
        ckpt_dir.mkdir()
        ckpt_path = ckpt_dir / f"checkpoint_{run_id_a}.json"
        ckpt_path.write_text("{}", encoding="utf-8")

        routes = [
            Route("/runs/{run_id}/resume", routes_runs.handle_resume_run, methods=["POST"]),
        ]
        app_b = _build_app(routes, CTX_B, manager)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post(f"/runs/{run_id_a}/resume", json={})
            assert resp.status_code == 404, (
                f"Expected 404 cross-tenant resume; got {resp.status_code}: {resp.text}"
            )


# ---------------------------------------------------------------------------
# 3. /replay/{run_id} — replay trigger and status
# ---------------------------------------------------------------------------


class TestCrossTenantReplay:
    """POST /replay/{run_id} and GET /replay/{run_id}/status — Tenant B blocked."""

    def test_tenant_b_cannot_trigger_replay_of_tenant_a_run(
        self, manager, tmp_path, monkeypatch
    ):
        # Tenant A creates a run and stages a replay JSONL file.
        run_id_a = _create_run(manager, CTX_A, goal="A-replay")
        monkeypatch.chdir(tmp_path)
        replay_path = tmp_path / f"replay_{run_id_a}.jsonl"
        replay_path.write_text("", encoding="utf-8")

        from hi_agent.server import app as server_app

        routes = [
            Route("/replay/{run_id}", server_app.handle_replay_trigger, methods=["POST"]),
        ]
        app_b = _build_app(routes, CTX_B, manager)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post(f"/replay/{run_id_a}", json={})
            assert resp.status_code == 404, (
                f"Expected 404 cross-tenant replay; got {resp.status_code}: {resp.text}"
            )

    def test_tenant_b_cannot_get_replay_status_of_tenant_a_run(
        self, manager, tmp_path, monkeypatch
    ):
        run_id_a = _create_run(manager, CTX_A, goal="A-replay-status")
        monkeypatch.chdir(tmp_path)
        replay_path = tmp_path / f"replay_{run_id_a}.jsonl"
        replay_path.write_text("", encoding="utf-8")

        from hi_agent.server import app as server_app

        routes = [
            Route(
                "/replay/{run_id}/status",
                server_app.handle_replay_status,
                methods=["GET"],
            ),
        ]
        app_b = _build_app(routes, CTX_B, manager)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get(f"/replay/{run_id_a}/status")
            assert resp.status_code == 404, (
                f"Expected 404 cross-tenant replay status; got {resp.status_code}: {resp.text}"
            )


# ---------------------------------------------------------------------------
# 4. /long-ops/{op_id} and /long-ops/{op_id}/cancel
# ---------------------------------------------------------------------------


def _build_op_coordinator(tmp_path):
    """Build a real LongRunningOpCoordinator backed by a temporary SQLite store."""
    from hi_agent.experiment.coordinator import LongRunningOpCoordinator
    from hi_agent.experiment.op_store import LongRunningOpStore

    store = LongRunningOpStore(tmp_path / "ops.db")
    coord = LongRunningOpCoordinator(store=store)
    return coord, store


class TestCrossTenantLongOps:
    """GET /long-ops/{op_id} and POST /long-ops/{op_id}/cancel — Tenant B blocked."""

    def test_tenant_b_cannot_get_tenant_a_long_op(self, manager, tmp_path):
        from hi_agent.server import routes_ops

        coord, store = _build_op_coordinator(tmp_path)
        op_id = str(uuid.uuid4())
        store.create(
            op_id=op_id,
            backend="dummy",
            external_id="ext-1",
            submitted_at=time.time(),
            tenant_id="tenant-A",
            user_id="user-a",
        )

        routes = [
            Route("/long-ops/{op_id}", routes_ops.handle_get_long_op, methods=["GET"]),
        ]
        app_b = _build_app(routes, CTX_B, manager)
        app_b.state.agent_server.op_coordinator = coord
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get(f"/long-ops/{op_id}")
            assert resp.status_code == 404, resp.text

    def test_tenant_b_cannot_cancel_tenant_a_long_op(self, manager, tmp_path):
        from hi_agent.server import routes_ops

        coord, store = _build_op_coordinator(tmp_path)
        op_id = str(uuid.uuid4())
        store.create(
            op_id=op_id,
            backend="dummy",
            external_id="ext-2",
            submitted_at=time.time(),
            tenant_id="tenant-A",
            user_id="user-a",
        )

        routes = [
            Route(
                "/long-ops/{op_id}/cancel",
                routes_ops.handle_cancel_long_op,
                methods=["POST"],
            ),
        ]
        app_b = _build_app(routes, CTX_B, manager)
        app_b.state.agent_server.op_coordinator = coord
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post(f"/long-ops/{op_id}/cancel", json={})
            assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 5. /sessions — list, runs, archive
# ---------------------------------------------------------------------------


def _build_session_store(tmp_path) -> Any:
    from hi_agent.server.session_store import SessionStore

    store = SessionStore(db_path=str(tmp_path / "sessions.db"))
    store.initialize()
    return store


class TestCrossTenantSessions:
    """Session list, runs, and PATCH must not leak across tenants."""

    def test_tenant_b_cannot_see_tenant_a_sessions(self, manager, tmp_path):
        from hi_agent.server import routes_sessions

        store = _build_session_store(tmp_path)
        # Tenant A creates a session.
        sid_a = store.create(tenant_id="tenant-A", user_id="user-a", name="A-session")

        routes = [Route("/sessions", routes_sessions.handle_list_sessions, methods=["GET"])]
        app_b = _build_app(routes, CTX_B, manager)
        app_b.state.agent_server.session_store = store
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get("/sessions")
            assert resp.status_code == 200, resp.text
            session_ids = [s["session_id"] for s in resp.json().get("sessions", [])]
            assert sid_a not in session_ids, (
                f"Tenant B leaked Tenant A's session {sid_a}: {session_ids}"
            )

    def test_tenant_b_cannot_get_tenant_a_session_runs(self, manager, tmp_path):
        from hi_agent.server import routes_sessions

        store = _build_session_store(tmp_path)
        sid_a = store.create(tenant_id="tenant-A", user_id="user-a", name="A-runs")

        routes = [
            Route(
                "/sessions/{session_id}/runs",
                routes_sessions.handle_get_session_runs,
                methods=["GET"],
            )
        ]
        app_b = _build_app(routes, CTX_B, manager)
        app_b.state.agent_server.session_store = store
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get(f"/sessions/{sid_a}/runs")
            assert resp.status_code == 404, (
                f"Expected 404 cross-tenant session runs; got {resp.status_code}: {resp.text}"
            )

    def test_tenant_b_cannot_archive_tenant_a_session(self, manager, tmp_path):
        from hi_agent.server import routes_sessions

        store = _build_session_store(tmp_path)
        sid_a = store.create(tenant_id="tenant-A", user_id="user-a", name="A-archive")

        routes = [
            Route(
                "/sessions/{session_id}",
                routes_sessions.handle_patch_session,
                methods=["PATCH"],
            )
        ]
        app_b = _build_app(routes, CTX_B, manager)
        app_b.state.agent_server.session_store = store
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.patch(f"/sessions/{sid_a}", json={"status": "archived"})
            assert resp.status_code == 404, (
                f"Expected 404 cross-tenant archive; got {resp.status_code}: {resp.text}"
            )
        # And confirm Tenant A's session was NOT archived.
        rec = store.get(sid_a)
        assert rec is not None
        assert rec.status == "active", "Tenant A's session was wrongly archived"


# ---------------------------------------------------------------------------
# 6. /team/events — Tenant B does not see Tenant A's team events
# ---------------------------------------------------------------------------


class TestCrossTenantTeamEvents:
    """GET /team/events?team_space_id=ts-a — Tenant B sees an empty list."""

    def test_tenant_b_cannot_see_tenant_a_team_events(self, manager, tmp_path):
        from hi_agent.server import routes_team
        from hi_agent.server.team_event_store import TeamEvent, TeamEventStore

        store = TeamEventStore(db_path=str(tmp_path / "team.db"))
        store.initialize()
        # Tenant A publishes an event in team space "ts-a".
        store.insert(
            TeamEvent(
                event_id=str(uuid.uuid4()),
                tenant_id="tenant-A",
                team_space_id="ts-a",
                event_type="capability.discovered",
                payload_json="{}",
                source_run_id="run-a",
                source_user_id="user-a",
                source_session_id="",
                publish_reason="test",
                schema_version=1,
                created_at=time.time(),
            )
        )

        routes = [Route("/team/events", routes_team.handle_list_team_events, methods=["GET"])]
        # Tenant B is in the SAME team_space_id "ts-a" but a DIFFERENT tenant.
        ctx_b_in_ts_a = TenantContext(
            tenant_id="tenant-B", user_id="user-b", session_id="", team_id="ts-a"
        )
        app_b = _build_app(routes, ctx_b_in_ts_a, manager)
        app_b.state.agent_server.team_event_store = store
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get("/team/events")
            assert resp.status_code == 200, resp.text
            events = resp.json().get("events", [])
            # Tenant A's run id must not surface in Tenant B's list.
            source_run_ids = [e.get("source_run_id") for e in events]
            assert "run-a" not in source_run_ids, (
                f"Tenant B leaked Tenant A's team event: {events}"
            )


# ---------------------------------------------------------------------------
# 7. /artifacts — list and provenance
# ---------------------------------------------------------------------------


class TestCrossTenantArtifactsList:
    """GET /artifacts and GET /artifacts/{id}/provenance must not leak."""

    def test_tenant_b_cannot_list_tenant_a_artifact(self, manager):
        from hi_agent.artifacts.contracts import Artifact
        from hi_agent.artifacts.registry import ArtifactRegistry

        registry = ArtifactRegistry()
        artifact_a = Artifact(
            artifact_type="text",
            content="A-secret",
            tenant_id="tenant-A",
            project_id="proj-a",
        )
        registry.store(artifact_a)

        app_b = Starlette(routes=list(artifact_routes))
        app_b.state.agent_server = _FakeServer(manager)
        app_b.state.agent_server.artifact_registry = registry
        app_b.add_middleware(_InjectCtxMiddleware, ctx=CTX_B)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get("/artifacts")
            assert resp.status_code == 200, resp.text
            ids = [a["artifact_id"] for a in resp.json().get("artifacts", [])]
            assert artifact_a.artifact_id not in ids, (
                f"Tenant B leaked Tenant A's artifact: {ids}"
            )

    def test_tenant_b_cannot_get_tenant_a_artifact_provenance(self, manager):
        from hi_agent.artifacts.contracts import Artifact
        from hi_agent.artifacts.registry import ArtifactRegistry

        registry = ArtifactRegistry()
        artifact_a = Artifact(
            artifact_type="text",
            content="A-prov",
            tenant_id="tenant-A",
            project_id="proj-a",
            provenance={"step": "draft"},
        )
        registry.store(artifact_a)

        app_b = Starlette(routes=list(artifact_routes))
        app_b.state.agent_server = _FakeServer(manager)
        app_b.state.agent_server.artifact_registry = registry
        app_b.add_middleware(_InjectCtxMiddleware, ctx=CTX_B)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get(f"/artifacts/{artifact_a.artifact_id}/provenance")
            assert resp.status_code == 404, (
                f"Expected 404 cross-tenant provenance; got {resp.status_code}: {resp.text}"
            )
