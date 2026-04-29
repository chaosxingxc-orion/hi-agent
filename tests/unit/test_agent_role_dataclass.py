"""Unit tests for AgentRole, TeamSharedContext, and TeamRun dataclasses (P4.1)."""

from __future__ import annotations

import pytest
from hi_agent.contracts.team_runtime import AgentRole, TeamRun, TeamSharedContext


def test_agent_role_defaults():
    """AgentRole fields default to expected values."""
    role = AgentRole(role_id="r1", role_name="pi")
    assert role.model_tier == "tier_b"
    assert role.memory_scope == "private"
    assert role.capabilities == ()
    assert role.description == ""


def test_agent_role_immutable():
    """AgentRole is frozen — mutation raises an error."""
    role = AgentRole(role_id="r1", role_name="pi")
    with pytest.raises((AttributeError, TypeError)):
        role.role_id = "other"  # type: ignore[misc]  expiry_wave: Wave 17


def test_agent_role_custom_fields():
    """AgentRole accepts all custom field values."""
    role = AgentRole(
        role_id="r2",
        role_name="survey",
        model_tier="tier_a",
        capabilities=("search", "summarise"),
        memory_scope="shared",
        description="Literature survey agent",
    )
    assert role.model_tier == "tier_a"
    assert role.capabilities == ("search", "summarise")
    assert role.memory_scope == "shared"


def test_team_run_member_runs():
    """TeamRun stores member_runs as expected."""
    team = TeamRun(
        team_id="t1",
        project_id="proj-1",
        tenant_id="test-tenant",
        member_runs=(("pi", "run-pi"), ("survey", "run-s1")),
    )
    assert len(team.member_runs) == 2
    assert team.member_runs[0] == ("pi", "run-pi")
    assert team.member_runs[1] == ("survey", "run-s1")


def test_team_run_immutable():
    """TeamRun is frozen — mutation raises an error."""
    team = TeamRun(team_id="t1", project_id="proj-1", tenant_id="test-tenant")
    with pytest.raises((AttributeError, TypeError)):
        team.team_id = "other"  # type: ignore[misc]  expiry_wave: Wave 17


def test_team_shared_context_defaults():
    """TeamSharedContext fields default to empty tuples."""
    ctx = TeamSharedContext(team_id="t1", project_id="proj-1", tenant_id="test-tenant")
    assert ctx.artifact_handoff_ids == ()
    assert ctx.hypotheses == ()
    assert ctx.claims == ()
    assert ctx.phase_history == ()


def test_team_shared_context_immutable():
    """TeamSharedContext is frozen — mutation raises an error."""
    ctx = TeamSharedContext(team_id="t1", project_id="proj-1", tenant_id="test-tenant")
    with pytest.raises((AttributeError, TypeError)):
        ctx.project_id = "other"  # type: ignore[misc]  expiry_wave: Wave 17


def test_team_run_default_empty_members():
    """TeamRun with no member_runs starts empty."""
    team = TeamRun(team_id="t2", project_id="proj-2", tenant_id="test-tenant")
    assert team.member_runs == ()
