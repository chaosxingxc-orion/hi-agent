"""Tenant isolation: handle_skill_promote must enforce skill ownership by tenant (AX-F F1).

Gap confirmed in W21 audit: skill_evolver is a server-wide singleton.
POST /skills/{skill_id}/promote triggers global promotion of a challenger to champion —
no ownership check exists. Tenant B can promote a challenger in a skill owned by Tenant A,
affecting all tenants that use that skill. This is a high-severity gap because
promotion permanently changes which skill version is served as champion.
Tests are xfail until W22 implements per-tenant skill ownership enforcement.

Layer 2 — Integration: real route handlers wired via Starlette test client.
No MagicMock on the subsystem under test.
"""
from __future__ import annotations

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


class _OwnershipTrackingVersionManager:
    """Version manager stub tracking promote calls without ownership verification.

    Simulates the CURRENT (broken) behavior: promote_challenger accepts any
    skill_id from any tenant without checking ownership.
    """

    def __init__(self):
        self.promote_calls: list[dict] = []
        # Skills are global — no tenant_id on the skill definition
        self._champion: dict[str, str] = {
            "skill-owned-by-A": "v1-champion",
            "skill-owned-by-B": "v1-champion",
        }
        self._challenger: dict[str, str | None] = {
            "skill-owned-by-A": "v2-challenger",
            "skill-owned-by-B": "v2-challenger",
        }
        self._ownership: dict[str, str] = {
            "skill-owned-by-A": "isolation-tenant-A",
            "skill-owned-by-B": "isolation-tenant-B",
        }

    def promote_challenger(self, skill_id: str) -> bool:
        # No ownership check — any tenant can promote any skill's challenger
        challenger = self._challenger.get(skill_id)
        if challenger is None:
            return False
        self.promote_calls.append({
            "skill_id": skill_id,
            "promoted_version": challenger,
        })
        self._champion[skill_id] = challenger
        self._challenger[skill_id] = None
        return True

    def get_champion(self, skill_id: str) -> str | None:
        return self._champion.get(skill_id)


class _FakeEvolver:
    def __init__(self, version_manager: _OwnershipTrackingVersionManager) -> None:
        self._version_manager = version_manager


class _FakeServer:
    def __init__(self, evolver) -> None:
        self.skill_evolver = evolver


def _build_app(evolver, ctx: TenantContext) -> Starlette:
    from hi_agent.server.app import handle_skill_promote
    routes = [
        Route("/skills/{skill_id}/promote", handle_skill_promote, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.agent_server = _FakeServer(evolver)
    app.add_middleware(_InjectCtxMiddleware, ctx=ctx)
    return app


@pytest.mark.xfail(
    reason=(
        "handle_skill_promote: skill_evolver._version_manager has no per-tenant "
        "ownership model (W21 gap). promote_challenger() accepts any skill_id "
        "without verifying that the calling tenant owns the skill. Tenant B can "
        "promote a challenger in Tenant A's skill, changing the champion globally. "
        "Fix in W22: add tenant_id ownership check before promote; return 403 if "
        "the calling tenant does not own the skill."
    ),
    strict=False,
    expiry_wave="Wave 27",
)
class TestSkillPromoteTenantIsolationGap:
    """POST /skills/{skill_id}/promote cross-tenant denial tests (xfail — W21 gap)."""

    def test_tenant_b_cannot_promote_tenant_a_skill_challenger(self):
        """Tenant B promoting the challenger in Tenant A's skill must get 403.

        Currently FAILS: no ownership check — promote_challenger() proceeds for
        any authenticated caller.
        """
        vm = _OwnershipTrackingVersionManager()
        evolver = _FakeEvolver(vm)
        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")

        app_b = _build_app(evolver, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            resp = cb.post("/skills/skill-owned-by-A/promote")
            if resp.status_code == 503:
                pytest.skip("Skill evolver not configured")

        # Must be 403 — Tenant B does not own skill-owned-by-A.
        # Currently returns 200 {"skill_id": "skill-owned-by-A", "promoted": true}.
        assert resp.status_code == 403, (
            f"Expected 403 (cross-tenant promote denied), got {resp.status_code}: "
            f"{resp.text}"
        )

    def test_tenant_b_promote_does_not_change_tenant_a_champion(self):
        """Champion version must not change when Tenant B attempts unauthorized promotion.

        Currently FAILS: promote_challenger() writes to the global version store
        without tenant ownership verification.
        """
        vm = _OwnershipTrackingVersionManager()
        evolver = _FakeEvolver(vm)

        original_champion_a = vm.get_champion("skill-owned-by-A")

        # Tenant B attempts to promote Tenant A's skill challenger
        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")
        app_b = _build_app(evolver, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            cb.post("/skills/skill-owned-by-A/promote")

        # Tenant A's champion must not have changed
        current_champion_a = vm.get_champion("skill-owned-by-A")
        assert current_champion_a == original_champion_a, (
            f"Tenant B changed Tenant A's champion: "
            f"original={original_champion_a!r}, current={current_champion_a!r}. "
            "Cross-tenant skill promotion confirmed — high-severity isolation gap."
        )

    def test_promote_call_log_does_not_contain_cross_tenant_entry(self):
        """promote_calls log must not contain an entry for cross-tenant promote attempt.

        If the route correctly returns 403, the version manager's promote_calls
        must remain empty (the operation was blocked before reaching the store).
        """
        vm = _OwnershipTrackingVersionManager()
        evolver = _FakeEvolver(vm)
        ctx_b = TenantContext(tenant_id="isolation-tenant-B", user_id="user-b")

        app_b = _build_app(evolver, ctx_b)
        with TestClient(app_b, raise_server_exceptions=False) as cb:
            cb.post("/skills/skill-owned-by-A/promote")

        # The version manager must not have recorded a promote call for this
        # cross-tenant attempt.
        cross_tenant_promotes = [
            c for c in vm.promote_calls if c.get("skill_id") == "skill-owned-by-A"
        ]
        assert len(cross_tenant_promotes) == 0, (
            f"version_manager.promote_calls contains {len(cross_tenant_promotes)} "
            f"cross-tenant promote entry(ies): {cross_tenant_promotes}. "
            "The route must block the call before it reaches the version store."
        )


class TestSkillPromoteOwnerAccess:
    """POST /skills/{skill_id}/promote baseline: owner must retain access (AX-F F1)."""

    def test_tenant_a_can_promote_own_skill_challenger(self):
        """Tenant A can promote the challenger in a skill it owns — must return 200.

        This test verifies that the ownership check (W22 fix) does not break
        the legitimate owner's ability to promote their own skill.
        """
        vm = _OwnershipTrackingVersionManager()
        evolver = _FakeEvolver(vm)
        ctx_a = TenantContext(tenant_id="isolation-tenant-A", user_id="user-a")

        app_a = _build_app(evolver, ctx_a)
        with TestClient(app_a, raise_server_exceptions=False) as ca:
            resp = ca.post("/skills/skill-owned-by-A/promote")
            if resp.status_code == 503:
                pytest.skip("Skill evolver not configured")

        assert resp.status_code == 200, (
            f"Tenant A could not promote its own skill: {resp.status_code}: {resp.text}"
        )
