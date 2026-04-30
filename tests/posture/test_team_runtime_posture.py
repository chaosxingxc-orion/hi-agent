"""Posture-matrix coverage for team_runtime contracts (AX-B B5).

Covers:
  hi_agent/contracts/team_runtime.py — AgentRole, TeamSharedContext, TeamRun,
      TeamRunSpec

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture


# ---------------------------------------------------------------------------
# AgentRole
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_agent_role_instantiates_under_posture(monkeypatch, posture_name):
    """AgentRole must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import AgentRole

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    role = AgentRole(role_id="r1", role_name="lead")
    assert role.role_id == "r1"
    assert role.role_name == "lead"
    assert role.model_tier == "tier_b"
    assert role.memory_scope == "private"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_agent_role_memory_scope_values_under_posture(monkeypatch, posture_name):
    """AgentRole accepts all valid memory_scope values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import AgentRole

    for scope in ("private", "shared", "both"):
        role = AgentRole(role_id="r1", role_name="worker", memory_scope=scope)
        assert role.memory_scope == scope


# ---------------------------------------------------------------------------
# TeamSharedContext
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_team_shared_context_instantiates_under_posture(monkeypatch, posture_name):
    """TeamSharedContext must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import TeamSharedContext

    ctx = TeamSharedContext(team_id="t1", project_id="p1", tenant_id="tenant-abc")
    assert ctx.team_id == "t1"
    assert ctx.project_id == "p1"
    assert ctx.tenant_id == "tenant-abc"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_team_shared_context_requires_team_id(monkeypatch, posture_name):
    """TeamSharedContext without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import TeamSharedContext

    with pytest.raises(TypeError):
        TeamSharedContext()  # missing team_id, project_id, tenant_id


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_team_shared_context_deprecated_hypotheses(monkeypatch, posture_name):
    """TeamSharedContext.hypotheses deprecated alias populates working_set."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import TeamSharedContext

    with pytest.warns(DeprecationWarning, match="hypotheses"):
        ctx = TeamSharedContext(
            team_id="t1",
            project_id="p1",
            tenant_id="t-abc",
            hypotheses=("h1", "h2"),
        )
    assert ctx.working_set == ("h1", "h2")


# ---------------------------------------------------------------------------
# TeamRun
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_team_run_instantiates_under_posture(monkeypatch, posture_name):
    """TeamRun must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import TeamRun

    run = TeamRun(team_id="t1", project_id="p1", tenant_id="tenant-abc")
    assert run.team_id == "t1"
    assert run.project_id == "p1"
    assert run.tenant_id == "tenant-abc"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_team_run_requires_tenant_id(monkeypatch, posture_name):
    """TeamRun without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import TeamRun

    with pytest.raises(TypeError):
        TeamRun()  # missing team_id, project_id, tenant_id


# ---------------------------------------------------------------------------
# TeamRunSpec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_team_run_spec_instantiates_under_posture(monkeypatch, posture_name):
    """TeamRunSpec must be instantiable with required fields under all postures.

    Under research/prod the spine field tenant_id is required (Rule 12).
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import TeamRunSpec

    tenant_id = "" if posture_name == "dev" else "tenant-abc"
    spec = TeamRunSpec(team_id="t1", project_id="p1", profile_id="prof1", tenant_id=tenant_id)
    assert spec.team_id == "t1"
    assert spec.project_id == "p1"
    assert spec.profile_id == "prof1"
    assert spec.roles == ()
    assert spec.phases == ()
    assert spec.tenant_id == tenant_id


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_team_run_spec_with_roles_under_posture(monkeypatch, posture_name):
    """TeamRunSpec with AgentRole tuples is valid under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import AgentRole, TeamRunSpec

    roles = (AgentRole(role_id="r1", role_name="lead"),)
    tenant_id = "" if posture_name == "dev" else "tenant-abc"
    spec = TeamRunSpec(
        team_id="t1", project_id="p1", profile_id="prof1", roles=roles, tenant_id=tenant_id
    )
    assert len(spec.roles) == 1
    assert spec.tenant_id == tenant_id
