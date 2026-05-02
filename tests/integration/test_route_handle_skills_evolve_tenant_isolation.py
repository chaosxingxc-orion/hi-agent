"""Tenant isolation: skills evolve path is tenant-scoped at the registry (W31 T-5').

Pre-W31: ``SkillRegistry.list_certified`` / ``list_applicable`` returned every
tenant's skills, so a cycle of evolution triggered by tenant B could iterate
over (and modify) tenant A's certified skills.  W31 T-5' adds a ``tenant_id``
filter to those reads; under research/prod posture an unscoped read raises.

Layer 2 — Integration: real ``SkillRegistry`` instances.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _seed_certified(registry, *, tenant_id: str, skill_id: str, scope: str = "*") -> None:
    from hi_agent.skill.registry import ManagedSkill

    registry._skills[skill_id] = ManagedSkill(
        skill_id=skill_id,
        name=skill_id,
        description=f"d-{skill_id}",
        lifecycle_stage="certified",
        applicability_scope=scope,
        tenant_id=tenant_id,
        evidence_count=5,
        success_count=5,
    )


class TestSkillsEvolveTenantIsolation:
    """A tenant-scoped evolve cycle iterates only over its own skills."""

    def test_list_applicable_filters_by_tenant(self):
        """``list_applicable(family, stage, tenant_id=B)`` returns only B-owned skills."""
        from hi_agent.skill.registry import SkillRegistry

        registry = SkillRegistry()
        _seed_certified(
            registry, tenant_id="isolation-tenant-A", skill_id="skill-A1", scope="*"
        )
        _seed_certified(
            registry, tenant_id="isolation-tenant-A", skill_id="skill-A2", scope="*"
        )
        _seed_certified(
            registry, tenant_id="isolation-tenant-B", skill_id="skill-B1", scope="*"
        )

        b_applicable = registry.list_applicable(
            "any-family", "stage-1", tenant_id="isolation-tenant-B"
        )
        ids = {s.skill_id for s in b_applicable}
        assert ids == {"skill-B1"}, (
            f"Tenant B's applicable-skill set contains tenant A's skills: {ids}"
        )

        a_applicable = registry.list_applicable(
            "any-family", "stage-1", tenant_id="isolation-tenant-A"
        )
        a_ids = {s.skill_id for s in a_applicable}
        assert a_ids == {"skill-A1", "skill-A2"}

    def test_strict_posture_unscoped_list_applicable_raises(self, monkeypatch):
        """Under research posture an unscoped ``list_applicable`` raises ValueError."""
        from hi_agent.skill.registry import SkillRegistry

        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        registry = SkillRegistry()
        with pytest.raises(ValueError, match="tenant_id"):
            registry.list_applicable("any-family", "stage-1")
