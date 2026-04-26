"""Track W2-A: SkillObserver read-path tenant filtering.

Verifies that when a tenant_id is passed to ``SkillObserver.get_observations``,
``get_metrics``, or ``get_all_metrics``, results are scoped to that tenant
only — no cross-tenant data leaks through the shared JSONL pool.

Also verifies the HTTP boundary: GET /skills/{id}/metrics for Tenant B does
not surface any data from Tenant A's executions, even when the underlying
observer is the cross-tenant server-singleton.

Layer 2 — Integration: real SkillObserver, real JSONL pool, real route
handlers.  No MagicMock on the subsystem under test.
"""

from __future__ import annotations

import pytest
from hi_agent.server.tenant_context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from hi_agent.skill.observer import (
    SkillObservation,
    SkillObserver,
    make_observation_id,
)
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def _obs(
    skill_id: str,
    tenant_id: str,
    *,
    success: bool = True,
    quality: float = 0.9,
    tokens: int = 100,
) -> SkillObservation:
    return SkillObservation(
        observation_id=make_observation_id(),
        skill_id=skill_id,
        skill_version="1.0.0",
        run_id=f"run-{tenant_id}",
        stage_id="stage-1",
        timestamp="2026-04-26T00:00:00Z",
        success=success,
        input_summary="in",
        output_summary="out",
        quality_score=quality,
        tokens_used=tokens,
        latency_ms=10,
        tenant_id=tenant_id,
        user_id=f"user-{tenant_id}",
        session_id=f"sess-{tenant_id}",
        project_id=f"proj-{tenant_id}",
    )


def test_get_observations_filters_by_tenant_id(tmp_path):
    """Two tenants share skill_id → tenant A sees only A's observations."""
    obs = SkillObserver(storage_dir=str(tmp_path / "obs"))
    skill_id = "s1"
    obs.observe(_obs(skill_id, "tenant-A"))
    obs.observe(_obs(skill_id, "tenant-A"))
    obs.observe(_obs(skill_id, "tenant-B"))
    obs.observe(_obs(skill_id, "tenant-B"))
    obs.observe(_obs(skill_id, "tenant-B"))

    a_only = obs.get_observations(skill_id, tenant_id="tenant-A")
    b_only = obs.get_observations(skill_id, tenant_id="tenant-B")

    assert len(a_only) == 2
    assert len(b_only) == 3
    assert all(o.tenant_id == "tenant-A" for o in a_only)
    assert all(o.tenant_id == "tenant-B" for o in b_only)

    # Legacy unscoped call returns the full pool (back-compat).
    full = obs.get_observations(skill_id)
    assert len(full) == 5


def test_get_metrics_aggregates_only_filtered_subset(tmp_path):
    """get_metrics(tenant_id=...) aggregates only that tenant's stream."""
    obs = SkillObserver(storage_dir=str(tmp_path / "obs"))
    skill_id = "s2"
    # Tenant A: 2 success, 0 failure
    obs.observe(_obs(skill_id, "tenant-A", success=True, quality=1.0))
    obs.observe(_obs(skill_id, "tenant-A", success=True, quality=1.0))
    # Tenant B: 1 success, 2 failure
    obs.observe(_obs(skill_id, "tenant-B", success=True, quality=0.2))
    obs.observe(_obs(skill_id, "tenant-B", success=False, quality=0.1))
    obs.observe(_obs(skill_id, "tenant-B", success=False, quality=0.0))

    m_a = obs.get_metrics(skill_id, tenant_id="tenant-A")
    m_b = obs.get_metrics(skill_id, tenant_id="tenant-B")

    assert m_a.total_executions == 2
    assert m_a.success_count == 2
    assert m_a.success_rate == 1.0

    assert m_b.total_executions == 3
    assert m_b.success_count == 1
    assert m_b.failure_count == 2
    assert m_b.success_rate == pytest.approx(1 / 3)


def test_get_all_metrics_filters_per_skill_by_tenant(tmp_path):
    """get_all_metrics(tenant_id=...) filters every skill's stream."""
    obs = SkillObserver(storage_dir=str(tmp_path / "obs"))
    obs.observe(_obs("s-x", "tenant-A"))
    obs.observe(_obs("s-x", "tenant-B"))
    obs.observe(_obs("s-y", "tenant-A"))
    obs.observe(_obs("s-y", "tenant-A"))
    obs.observe(_obs("s-y", "tenant-B"))
    obs.observe(_obs("s-y", "tenant-B"))
    obs.observe(_obs("s-y", "tenant-B"))

    by_a = obs.get_all_metrics(tenant_id="tenant-A")
    by_b = obs.get_all_metrics(tenant_id="tenant-B")

    assert by_a["s-x"].total_executions == 1
    assert by_a["s-y"].total_executions == 2
    assert by_b["s-x"].total_executions == 1
    assert by_b["s-y"].total_executions == 3


# ---------------------------------------------------------------------------
# HTTP boundary test — Tenant B must not see Tenant A's metrics
# ---------------------------------------------------------------------------


class _InjectCtxMiddleware(BaseHTTPMiddleware):
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


class _FakeEvolver:
    def __init__(self, observer: SkillObserver) -> None:
        self._observer = observer


class _FakeServer:
    def __init__(self, observer: SkillObserver) -> None:
        self.skill_evolver = _FakeEvolver(observer)
        self.skill_loader = None


def _build_app(observer: SkillObserver, ctx: TenantContext) -> Starlette:
    from hi_agent.server.app import handle_skill_metrics

    app = Starlette(
        routes=[
            Route(
                "/skills/{skill_id}/metrics",
                handle_skill_metrics,
                methods=["GET"],
            ),
        ]
    )
    app.state.agent_server = _FakeServer(observer)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


CTX_A = TenantContext(tenant_id="tenant-A", user_id="user-a", session_id="")
CTX_B = TenantContext(tenant_id="tenant-B", user_id="user-b", session_id="")


def test_http_skill_metrics_does_not_leak_across_tenants(tmp_path):
    """GET /skills/{id}/metrics: Tenant B does not see Tenant A's data."""
    observer = SkillObserver(storage_dir=str(tmp_path / "obs"))
    skill_id = "shared-skill"

    # Tenant A: 5 successful executions, all high quality
    for _ in range(5):
        observer.observe(_obs(skill_id, "tenant-A", success=True, quality=1.0))

    # Tenant B has never executed this skill.
    app_b = _build_app(observer, CTX_B)
    with TestClient(app_b, raise_server_exceptions=False) as cb:
        resp = cb.get(f"/skills/{skill_id}/metrics")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Tenant B sees zero executions — no leakage of A's stream.
        assert body["total_executions"] == 0, (
            f"cross-tenant leak: Tenant B sees Tenant A's metrics: {body!r}"
        )
        assert body["success_count"] == 0
        assert body["success_rate"] == 0.0

    # Tenant A still sees its own data.
    app_a = _build_app(observer, CTX_A)
    with TestClient(app_a, raise_server_exceptions=False) as ca:
        resp_a = ca.get(f"/skills/{skill_id}/metrics")
        assert resp_a.status_code == 200, resp_a.text
        body_a = resp_a.json()
        assert body_a["total_executions"] == 5
        assert body_a["success_count"] == 5
