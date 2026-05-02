"""Tenant isolation: skill promote path is tenant-scoped at the registry (W31 T-5').

Pre-W31: a tenant could resolve any skill_id via the global registry and
promote/deprecate/retire it.  W31 T-5' adds a ``tenant_id`` argument to
every read method on ``SkillRegistry``; combined with the route-layer
ownership check (A2 territory), unauthorized cross-tenant promotions fail.

This file pins the registry-layer behaviour: ``get(skill_id, tenant_id=B)``
must return ``None`` for an A-owned skill, so a downstream lifecycle write
that depends on a successful lookup cannot reach a foreign skill.

Layer 2 — Integration: real ``SkillRegistry`` instances.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _seed_certified(registry, *, tenant_id: str, skill_id: str) -> None:
    from hi_agent.skill.registry import ManagedSkill

    registry._skills[skill_id] = ManagedSkill(
        skill_id=skill_id,
        name=skill_id,
        description=f"d-{skill_id}",
        lifecycle_stage="certified",
        applicability_scope="*",
        tenant_id=tenant_id,
        evidence_count=5,
        success_count=5,
    )


class TestSkillPromoteTenantIsolation:
    """Cross-tenant promote attempts cannot resolve the target skill."""

    def test_tenant_b_get_returns_none_for_tenant_a_skill(self):
        """Tenant B's lookup of an A-owned skill returns None (object-level 404)."""
        from hi_agent.skill.registry import SkillRegistry

        registry = SkillRegistry()
        _seed_certified(registry, tenant_id="isolation-tenant-A", skill_id="skill-A")

        assert registry.get("skill-A", tenant_id="isolation-tenant-B") is None
        # Sanity: legitimate owner still sees the skill.
        assert registry.get("skill-A", tenant_id="isolation-tenant-A") is not None

    def test_list_certified_does_not_leak_cross_tenant(self):
        """``list_certified(tenant_id='B')`` excludes tenant A's certified skills."""
        from hi_agent.skill.registry import SkillRegistry

        registry = SkillRegistry()
        _seed_certified(registry, tenant_id="isolation-tenant-A", skill_id="skill-A")
        _seed_certified(registry, tenant_id="isolation-tenant-B", skill_id="skill-B")

        b_view = registry.list_certified(tenant_id="isolation-tenant-B")
        ids = {s.skill_id for s in b_view}
        assert ids == {"skill-B"}, (
            f"Tenant B's certified-skill view leaked tenant A's skills: {ids}"
        )

    def test_strict_posture_unscoped_list_raises(self, monkeypatch):
        """Under research/prod posture an unscoped list raises ValueError."""
        from hi_agent.skill.registry import SkillRegistry

        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="tenant_id"):
            registry.list_by_stage("certified")  # tenant_id omitted
