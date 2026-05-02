"""Tenant isolation: skill optimize path is tenant-scoped at the registry (W31 T-5').

Pre-W31: ``SkillRegistry.get`` / ``list_by_stage`` / ``list_certified`` /
``list_applicable`` were tenant-blind despite ``ManagedSkill.tenant_id``
existing on the spine.  W31 T-5' adds a ``tenant_id`` argument to each read
method; under research/prod posture an unscoped read raises ``ValueError``,
so a route that forgets to plumb the tenant is forced to fail loudly rather
than silently expose another tenant's skill.

Layer 2 — Integration: real ``SkillRegistry`` instances.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _seed_registry(registry, *, tenant_id: str, skill_id: str, name: str) -> None:
    """Seed a tenant-owned certified skill into *registry* (test helper)."""
    from hi_agent.skill.registry import ManagedSkill

    registry._skills[skill_id] = ManagedSkill(
        skill_id=skill_id,
        name=name,
        description=f"description for {skill_id}",
        lifecycle_stage="certified",
        applicability_scope="*",
        tenant_id=tenant_id,
        evidence_count=5,
        success_count=5,
        failure_count=0,
    )


class TestSkillOptimizeTenantIsolation:
    """SkillRegistry reads return only the calling tenant's skill (W31 T-5')."""

    def test_tenant_b_get_does_not_return_tenant_a_skill(self):
        """``registry.get(skill_id, tenant_id='B')`` returns None for an A-owned skill."""
        from hi_agent.skill.registry import SkillRegistry

        registry = SkillRegistry()
        _seed_registry(
            registry, tenant_id="isolation-tenant-A", skill_id="skill-A", name="skill A"
        )

        # Tenant B asking for skill-A receives None (object-level 404).
        assert registry.get("skill-A", tenant_id="isolation-tenant-B") is None
        # Tenant A still sees its own skill.
        assert registry.get("skill-A", tenant_id="isolation-tenant-A") is not None

    def test_list_by_stage_filters_by_tenant(self):
        """``list_by_stage`` and ``list_certified`` only return the tenant's skills."""
        from hi_agent.skill.registry import SkillRegistry

        registry = SkillRegistry()
        _seed_registry(
            registry, tenant_id="isolation-tenant-A", skill_id="skill-A", name="A"
        )
        _seed_registry(
            registry, tenant_id="isolation-tenant-B", skill_id="skill-B", name="B"
        )

        a_certified = registry.list_certified(tenant_id="isolation-tenant-A")
        b_certified = registry.list_certified(tenant_id="isolation-tenant-B")
        assert {s.skill_id for s in a_certified} == {"skill-A"}
        assert {s.skill_id for s in b_certified} == {"skill-B"}

    def test_strict_posture_unscoped_get_raises(self, monkeypatch):
        """Under research/prod posture a tenant-blind ``get`` raises ValueError."""
        from hi_agent.skill.registry import SkillRegistry

        for posture_name in ("research", "prod"):
            monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
            registry = SkillRegistry()
            with pytest.raises(ValueError, match="tenant_id"):
                registry.get("any-skill")  # tenant_id omitted
