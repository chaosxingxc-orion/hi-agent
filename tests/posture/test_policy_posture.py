"""Posture-matrix coverage for policy contracts (AX-B B5).

Covers:
  hi_agent/contracts/policy.py — PolicyVersionSet, SkillContentSpec

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# PolicyVersionSet
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_policy_version_set_instantiates_under_posture(monkeypatch, posture_name):
    """PolicyVersionSet must be instantiable with defaults under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.policy import PolicyVersionSet

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    pvs = PolicyVersionSet()
    assert pvs.route_policy == "route_v1"
    assert pvs.acceptance_policy == "acceptance_v1"
    assert pvs.memory_policy == "memory_v1"
    assert pvs.evaluation_policy == "evaluation_v1"
    assert pvs.task_view_policy == "task_view_v1"
    assert pvs.skill_policy == "skill_v1"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_policy_version_set_custom_versions_under_posture(monkeypatch, posture_name):
    """PolicyVersionSet with custom versions is valid under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.policy import PolicyVersionSet

    pvs = PolicyVersionSet(route_policy="route_v2", skill_policy="skill_v3")
    assert pvs.route_policy == "route_v2"
    assert pvs.skill_policy == "skill_v3"


# ---------------------------------------------------------------------------
# SkillContentSpec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_skill_content_spec_instantiates_under_posture(monkeypatch, posture_name):
    """SkillContentSpec must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.policy import SkillContentSpec

    spec = SkillContentSpec(
        skill_id="skill-001",
        version="1.0.0",
        checksum="abc123def456",
    )
    assert spec.skill_id == "skill-001"
    assert spec.version == "1.0.0"
    assert spec.checksum == "abc123def456"
    assert spec.side_effect_class == "read_only"
    assert spec.rollback_policy == "none"
    assert spec.lifecycle_stage == "candidate"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_skill_content_spec_requires_required_fields(monkeypatch, posture_name):
    """SkillContentSpec without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.policy import SkillContentSpec

    with pytest.raises(TypeError):
        SkillContentSpec()  # missing skill_id, version, checksum


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_skill_content_spec_lifecycle_stages_under_posture(monkeypatch, posture_name):
    """SkillContentSpec accepts all lifecycle_stage values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.policy import SkillContentSpec

    for stage in ("candidate", "provisional", "certified", "deprecated", "retired"):
        spec = SkillContentSpec(
            skill_id="s1", version="1.0", checksum="x", lifecycle_stage=stage
        )
        assert spec.lifecycle_stage == stage
