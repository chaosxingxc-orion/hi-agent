"""Cross-tenant object-level access denial tests (Track F, Wave 10.1).

Verifies that authenticated Tenant B cannot access objects owned by Tenant A
on endpoints not covered by test_cross_tenant_isolation.py:
  - GET /artifacts/{artifact_id}
  - GET /artifacts/by-project/{project_id}
  - GET /runs/{run_id}/feedback
  - POST /runs/{run_id}/gate_decision  (ownership gate — same pattern)
  - GET /runs/{run_id}/reasoning-trace

Layer 2 — Integration: real RunManager, real ArtifactRegistry, real
FeedbackStore.  No MagicMock on the subsystem under test.
Uses _InjectCtxMiddleware (same pattern as test_cross_tenant_isolation.py).
"""
from __future__ import annotations

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
# Shared helpers (mirror test_cross_tenant_isolation.py)
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


def _build_runs_app(manager: RunManager, ctx: TenantContext) -> Starlette:
    """Build a minimal ASGI app with /runs routes and injected TenantContext."""
    routes = [
        Route("/runs", routes_runs.handle_list_runs, methods=["GET"]),
        Route("/runs", routes_runs.handle_create_run, methods=["POST"]),
        Route("/runs/{run_id}", routes_runs.handle_get_run, methods=["GET"]),
        Route("/runs/{run_id}/cancel", routes_runs.handle_cancel_run, methods=["POST"]),
        Route("/runs/{run_id}/feedback", routes_runs.handle_submit_feedback, methods=["POST"]),
        Route("/runs/{run_id}/feedback", routes_runs.handle_get_feedback, methods=["GET"]),
        Route(
            "/runs/{run_id}/gate_decision",
            routes_runs.handle_gate_decision,
            methods=["POST"],
        ),
        Route(
            "/runs/{run_id}/reasoning-trace",
            routes_runs.handle_reasoning_trace,
            methods=["GET"],
        ),
    ]
    app = Starlette(routes=routes)
    server = _FakeServer(manager)
    app.state.agent_server = server
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


def _build_artifacts_app(manager: RunManager, ctx: TenantContext) -> Starlette:
    """Build a minimal ASGI app with /artifacts routes and injected TenantContext."""
    app = Starlette(routes=list(artifact_routes))
    server = _FakeServer(manager)
    app.state.agent_server = server
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager():
    rm = RunManager()
    yield rm
    rm.shutdown()


CTX_A = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
CTX_B = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")


# ---------------------------------------------------------------------------
# Artifact isolation tests
# ---------------------------------------------------------------------------


class TestCrossTenantArtifactObjectLevel:
    """GET /artifacts/{id} — Tenant B cannot fetch Tenant A's artifact."""

    def test_tenant_b_cannot_get_tenant_a_artifact(self, manager):
        """Tenant A stores an artifact; GET by Tenant B must return 404."""
        from hi_agent.artifacts.contracts import Artifact
        from hi_agent.artifacts.registry import ArtifactRegistry

        registry = ArtifactRegistry()
        artifact = Artifact(
            artifact_type="text",
            content="secret",
            tenant_id="tenant-A",
            project_id="proj-a",
        )
        registry.store(artifact)

        # Tenant A: confirm artifact is accessible
        app_a = _build_artifacts_app(manager, CTX_A)
        app_a.state.agent_server.artifact_registry = registry
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            resp = ca.get(f"/artifacts/{artifact.artifact_id}")
            assert resp.status_code == 200, f"Tenant A should see own artifact: {resp.text}"

        # Tenant B: must not see Tenant A's artifact
        app_b = _build_artifacts_app(manager, CTX_B)
        app_b.state.agent_server.artifact_registry = registry
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp_b = cb.get(f"/artifacts/{artifact.artifact_id}")
            assert resp_b.status_code == 404, (
                f"Expected 404, got {resp_b.status_code}: {resp_b.text}"
            )

    def test_tenant_b_cannot_list_tenant_a_artifacts_in_project(self, manager):
        """GET /artifacts/by-project/{project_id} must not leak Tenant A artifacts to Tenant B."""
        from hi_agent.artifacts.contracts import Artifact
        from hi_agent.artifacts.registry import ArtifactRegistry

        registry = ArtifactRegistry()
        artifact = Artifact(
            artifact_type="text",
            content="private data",
            tenant_id="tenant-A",
            project_id="proj-secret",
        )
        registry.store(artifact)

        # Tenant B: project exists but belongs to Tenant A — must get 404 (not Tenant A's data)
        app_b = _build_artifacts_app(manager, CTX_B)
        app_b.state.agent_server.artifact_registry = registry
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get("/artifacts/by-project/proj-secret")
            # Route returns 404 when all candidates belong to a different tenant
            assert resp.status_code == 404, (
                f"Expected 404 (cross-tenant project), got {resp.status_code}: {resp.text}"
            )
            # Confirm Tenant A's artifact content is not in the response body
            assert artifact.artifact_id not in resp.text


# ---------------------------------------------------------------------------
# Feedback isolation tests
# ---------------------------------------------------------------------------


class TestCrossTenantFeedbackIsolation:
    """GET /runs/{run_id}/feedback — Tenant B cannot read Tenant A's feedback."""

    def test_tenant_b_cannot_get_tenant_a_feedback(self, manager):
        """Tenant A creates a run + submits feedback; Tenant B GET returns 404."""
        from hi_agent.evolve.feedback_store import FeedbackStore

        # Tenant A: create run
        app_a = _build_runs_app(manager, CTX_A)
        feedback_store = FeedbackStore()
        app_a.state.agent_server._feedback_store = feedback_store

        with TestClient(app_a, raise_server_exceptions=False) as ca:
            r = ca.post("/runs", json={"goal": "tenant A feedback task"})
            assert r.status_code in (200, 201, 202), f"create failed: {r.text}"
            run_id = r.json().get("run_id")
            assert run_id

            # Submit feedback as Tenant A
            r2 = ca.post(f"/runs/{run_id}/feedback", json={"rating": 1.0, "notes": "great"})
            assert r2.status_code == 200, f"feedback submit failed: {r2.text}"

        # Tenant B: must not retrieve Tenant A's feedback
        app_b = _build_runs_app(manager, CTX_B)
        app_b.state.agent_server._feedback_store = feedback_store
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get(f"/runs/{run_id}/feedback")
            assert resp.status_code == 404, (
                f"Expected 404, got {resp.status_code}: {resp.text}"
            )


# ---------------------------------------------------------------------------
# Gate decision isolation tests
# ---------------------------------------------------------------------------


class TestCrossTenantGateIsolation:
    """POST /runs/{run_id}/gate_decision — Tenant B cannot post a gate decision for Tenant A's run.
    """

    def test_tenant_b_cannot_gate_tenant_a_run(self, manager):
        """Tenant A creates a run; Tenant B POST gate_decision must return 404."""
        # Tenant A: create run
        app_a = _build_runs_app(manager, CTX_A)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            r = ca.post("/runs", json={"goal": "tenant A gate task"})
            assert r.status_code in (200, 201, 202), f"create failed: {r.text}"
            run_id = r.json().get("run_id")
            assert run_id

        # Tenant B: attempt gate decision on Tenant A's run
        app_b = _build_runs_app(manager, CTX_B)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post(
                f"/runs/{run_id}/gate_decision",
                json={
                    "decision": "approve",
                    "approver_id": "user-b",
                },
            )
            assert resp.status_code == 404, (
                f"Expected 404, got {resp.status_code}: {resp.text}"
            )


# ---------------------------------------------------------------------------
# Reasoning trace isolation tests
# ---------------------------------------------------------------------------


class TestCrossTenantReasoningTraceIsolation:
    """GET /runs/{run_id}/reasoning-trace — Tenant B cannot read Tenant A's trace."""

    def test_tenant_b_cannot_get_tenant_a_reasoning_trace(self, manager):
        """Tenant A creates a run; Tenant B GET reasoning-trace must return 404."""
        # Tenant A: create run
        app_a = _build_runs_app(manager, CTX_A)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            r = ca.post("/runs", json={"goal": "tenant A trace task"})
            assert r.status_code in (200, 201, 202), f"create failed: {r.text}"
            run_id = r.json().get("run_id")
            assert run_id

        # Tenant B: must get 404 (run not found in Tenant B's scope)
        app_b = _build_runs_app(manager, CTX_B)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.get(f"/runs/{run_id}/reasoning-trace")
            assert resp.status_code == 404, (
                f"Expected 404, got {resp.status_code}: {resp.text}"
            )
