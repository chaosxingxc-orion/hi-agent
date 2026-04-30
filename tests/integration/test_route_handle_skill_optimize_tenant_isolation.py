"""Tenant isolation: handle_skill_optimize must only optimize the calling tenant's skills (AX-F F1).

Gap confirmed in W21 audit: skill_evolver is a server-wide singleton.
POST /skills/{skill_id}/optimize triggers prompt optimization on a GLOBAL skill —
Tenant B can optimize (and potentially degrade) a skill that Tenant A depends on,
or optimize a skill it does not own. No ownership check is performed.
Tests are xfail until W22 implements per-tenant skill ownership enforcement.

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
class _FakeVersionRecord:
    version: str
    is_champion: bool
    is_challenger: bool
    created_at: str = "2026-04-29T00:00:00Z"


class _OwnershipTrackingEvolver:
    """Skill evolver stub that tracks optimize calls per skill and records tenant context.

    Simulates the CURRENT (broken) behavior: optimize_prompt and deploy_optimization
    do not receive or validate tenant_id — any tenant can optimize any skill.
    """

    def __init__(self):
        self.optimize_calls: list[dict] = []
        # Skills are global — no tenant_id on the skill definition
        self._skills: dict[str, dict] = {
            "skill-owned-by-A": {"owner_tenant": "isolation-tenant-A", "prompt": "original"},
            "skill-owned-by-B": {"owner_tenant": "isolation-tenant-B", "prompt": "original"},
        }

    def optimize_prompt(self, skill_id: str) -> str | None:
        # No ownership check — any caller can optimize any skill
        self.optimize_calls.append({"skill_id": skill_id, "stage": "optimize_prompt"})
        if skill_id in self._skills:
            return f"optimized-prompt-for-{skill_id}"
        return None

    def deploy_optimization(self, skill_id: str, new_prompt: str) -> _FakeVersionRecord:
        # No ownership check — any caller can deploy to any skill
        self.optimize_calls.append({
            "skill_id": skill_id,
            "stage": "deploy_optimization",
            "new_prompt": new_prompt,
        })
        if skill_id in self._skills:
            self._skills[skill_id]["prompt"] = new_prompt
        return _FakeVersionRecord(
            version="v2",
            is_champion=False,
            is_challenger=True,
        )


class _FakeServer:
    def __init__(self, evolver) -> None:
        self.skill_evolver = evolver


def _build_app(evolver, ctx: TenantContext) -> Starlette:
    from hi_agent.server.app import handle_skill_optimize
    routes = [
        Route("/skills/{skill_id}/optimize", handle_skill_optimize, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(evolver)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.mark.xfail(
    reason=(
        "handle_skill_optimize: skill_evolver has no per-tenant ownership model "
        "(W21 gap). optimize_prompt() and deploy_optimization() accept any skill_id "
        "without verifying that the calling tenant owns the skill. Tenant B can "
        "optimize (potentially degrading) a skill owned by Tenant A. "
        "Fix in W22: add tenant_id ownership check before allowing optimize; "
        "return 403 if calling tenant does not own the skill."
    ),
    strict=False,
    expiry_wave="Wave 26",
)
class TestSkillOptimizeTenantIsolationGap:
    """POST /skills/{skill_id}/optimize cross-tenant denial tests (xfail — W21 gap)."""

    def test_tenant_b_cannot_optimize_tenant_a_skill(self):
        """Tenant B optimizing a skill owned by Tenant A must get 403.

        Currently FAILS: no ownership check — any authenticated tenant can
        optimize any skill in the global registry.
        """
        evolver = _OwnershipTrackingEvolver()
        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")

        app_b = _build_app(evolver, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post("/skills/skill-owned-by-A/optimize")
            if resp.status_code == 503:
                pytest.skip("Skill evolver not configured")

        # Must be 403 (Tenant B does not own skill-owned-by-A).
        # Currently returns 200 (optimized=True) — ownership gap confirmed.
        assert resp.status_code == 403, (
            f"Expected 403 (cross-tenant optimize denied), got {resp.status_code}: "
            f"{resp.text}"
        )

    def test_optimize_does_not_mutate_other_tenant_skill_prompt(self):
        """Prompt mutation via optimize must be gated to the skill owner.

        Currently FAILS: deploy_optimization writes to the global skill store
        without tenant ownership verification.
        """
        evolver = _OwnershipTrackingEvolver()
        original_prompt = evolver._skills["skill-owned-by-A"]["prompt"]

        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")
        app_b = _build_app(evolver, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            cb.post("/skills/skill-owned-by-A/optimize")

        # Tenant A's skill prompt must NOT have been modified by Tenant B.
        current_prompt = evolver._skills["skill-owned-by-A"]["prompt"]
        assert current_prompt == original_prompt, (
            f"Tenant B mutated Tenant A's skill prompt: "
            f"original={original_prompt!r}, current={current_prompt!r}. "
            "Cross-tenant skill mutation confirmed."
        )


class TestSkillOptimizeOwnerAccess:
    """POST /skills/{skill_id}/optimize baseline: owner must retain access (AX-F F1)."""

    def test_tenant_a_can_optimize_own_skill(self):
        """Tenant A can optimize a skill it owns — must return 200.

        This test verifies that the fix (ownership check in W22) does not break
        the legitimate owner's ability to optimize their own skill.
        """
        evolver = _OwnershipTrackingEvolver()
        ctx_a = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")

        app_a = _build_app(evolver, ctx_a)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            resp = ca.post("/skills/skill-owned-by-A/optimize")
            if resp.status_code == 503:
                pytest.skip("Skill evolver not configured")

        # Legitimate owner must be able to optimize their own skill.
        assert resp.status_code == 200, (
            f"Tenant A could not optimize its own skill: {resp.status_code}: {resp.text}"
        )
