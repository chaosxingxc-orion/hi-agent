"""Tenant isolation: handle_skills_evolve must scope evolution to the calling tenant (AX-F F1).

Gap confirmed in W21 audit: skill_evolver is a server-wide singleton.
POST /skills/evolve triggers a global evolution cycle affecting ALL tenants' skills.
Tenant B calling evolve could modify skills that Tenant A depends on.
Tests are xfail until W22 implements per-tenant skill scoping.

Layer 2 — Integration: real route handlers wired via Starlette test client.
No MagicMock on the subsystem under test.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
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


class _InjectCtxMiddleware(BaseHTTPMiddleware):
    """Injects a fixed TenantContext per request."""

    def __init__(self, app, ctx: TenantContext) -> None:
        super().__init__(app)
        self._ctx = ctx

    async def dispatch(self, request: Request, call_next):
        token = set_tenant_context(self._ctx)
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token)


@dataclass
class _FakeEvolutionReport:
    """Mirrors the EvolutionReport dataclass returned by evolver.evolve_cycle()."""
    skills_evaluated: int = 0
    skills_evolved: int = 0
    cycles_run: int = 1
    tenant_id: str = ""  # Would be populated in a correct implementation


class _GlobalSkillEvolver:
    """Skill evolver stub simulating the CURRENT global-evolution behavior.

    evolve_cycle() operates on all skills without tenant scoping.
    Records which tenants triggered evolution to detect cross-tenant impact.
    """

    def __init__(self):
        self.evolution_calls: list[dict] = []
        # Simulate 3 global skills belonging to different tenants
        self._global_skills = [
            {"skill_id": "skill-A1", "owner_tenant": "isolation-tenant-A"},
            {"skill_id": "skill-A2", "owner_tenant": "isolation-tenant-A"},
            {"skill_id": "skill-B1", "owner_tenant": "isolation-tenant-B"},
        ]

    def evolve_cycle(self) -> _FakeEvolutionReport:
        # Current behavior: evolves ALL skills regardless of calling tenant
        self.evolution_calls.append({"scope": "global", "skills_evolved": len(self._global_skills)})
        return _FakeEvolutionReport(
            skills_evaluated=len(self._global_skills),
            skills_evolved=len(self._global_skills),
        )

    def evolve_cycle_for_tenant(self, tenant_id: str) -> _FakeEvolutionReport:
        """What a correct implementation would look like."""
        tenant_skills = [s for s in self._global_skills if s["owner_tenant"] == tenant_id]
        self.evolution_calls.append({
            "scope": "tenant",
            "tenant_id": tenant_id,
            "skills_evolved": len(tenant_skills),
        })
        return _FakeEvolutionReport(
            skills_evaluated=len(tenant_skills),
            skills_evolved=len(tenant_skills),
            tenant_id=tenant_id,
        )


class _FakeServer:
    def __init__(self, evolver) -> None:
        self.skill_evolver = evolver
        self.skill_loader = None


def _build_app(evolver, ctx: TenantContext) -> Starlette:
    from hi_agent.server.app import handle_skills_evolve
    routes = [Route("/skills/evolve", handle_skills_evolve, methods=["POST"])]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(evolver)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.mark.xfail(
    reason=(
        "handle_skills_evolve: skill_evolver is a global singleton with no "
        "per-tenant scope (W21 gap). evolve_cycle() evolves ALL tenants' skills "
        "regardless of who triggered it, enabling Tenant B to inadvertently "
        "modify skills owned by Tenant A. "
        "Fix in W22: pass tenant_id to evolve_cycle() and restrict evolution scope."
    ),
    strict=False,
)
class TestSkillsEvolveTenantIsolation:
    """POST /skills/evolve must only evolve the calling tenant's skills (AX-F F1)."""

    def test_tenant_b_evolve_does_not_modify_tenant_a_skills(self):
        """Tenant B triggering evolve must only affect Tenant B's own skills.

        Currently FAILS: evolve_cycle() is global — it evolves skills belonging
        to ALL tenants including Tenant A.
        """
        evolver = _GlobalSkillEvolver()
        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")

        app_b = _build_app(evolver, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post("/skills/evolve")
            if resp.status_code == 503:
                pytest.skip("Skill evolver not configured on this test instance")
            assert resp.status_code == 200, f"Evolve failed: {resp.text}"
            body = resp.json()
            skills_evaluated = body.get("skills_evaluated", 0)

        # Tenant B owns 1 skill. A tenant-scoped evolve must only evaluate 1.
        # Current broken behavior evaluates all 3 (both tenants' skills).
        assert skills_evaluated <= 1, (
            f"Tenant B's evolve cycle evaluated {skills_evaluated} skills; "
            f"expected <=1 (only Tenant B's skills). "
            f"Tenant A's skills were included in the evolve scope."
        )

        # Verify the evolution call recorded the correct scope
        assert len(evolver.evolution_calls) == 1
        call = evolver.evolution_calls[0]
        assert call.get("scope") != "global", (
            f"Evolution scope was 'global' instead of 'tenant': {call}. "
            "Cross-tenant skill mutation confirmed."
        )

    def test_evolve_response_carries_tenant_scope(self):
        """EvolutionReport returned by evolve must identify the calling tenant.

        Currently FAILS: _FakeEvolutionReport has tenant_id="" because
        evolve_cycle() does not receive or record tenant_id.
        """
        evolver = _GlobalSkillEvolver()
        ctx = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")

        app = _build_app(evolver, ctx)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/skills/evolve")
            if resp.status_code == 503:
                pytest.skip("Skill evolver not configured")
            assert resp.status_code == 200
            body = resp.json()

        # A correctly scoped report must include tenant_id
        assert "tenant_id" in body, (
            f"EvolutionReport missing tenant_id field: {body}. "
            "Correct implementation must embed tenant_id in the evolution report."
        )
        assert body.get("tenant_id") == "isolation-tenant-A", (
            f"tenant_id={body.get('tenant_id')!r}, expected 'isolation-tenant-A'"
        )
