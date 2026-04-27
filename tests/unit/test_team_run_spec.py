"""Unit tests: TeamRunSpec platform-neutral contract.

CO-7: verifies construction, field defaults, and that TeamRunSpec is a pure
data declaration (no runtime state, no side effects on construction).
"""

from __future__ import annotations

import pytest
from hi_agent.contracts.team_runtime import AgentRole, TeamRunSpec


def _make_role(role_id: str = "pi", role_name: str = "pi") -> AgentRole:
    return AgentRole(role_id=role_id, role_name=role_name)


def test_team_run_spec_minimal_construction() -> None:
    """TeamRunSpec must be constructable with only required fields."""
    spec = TeamRunSpec(team_id="team-1", project_id="proj-1", profile_id="default")
    assert spec.team_id == "team-1"
    assert spec.project_id == "proj-1"
    assert spec.profile_id == "default"


def test_team_run_spec_field_defaults() -> None:
    """All optional fields must default to empty collections."""
    spec = TeamRunSpec(team_id="t", project_id="p", profile_id="prof")
    assert spec.roles == ()
    assert spec.phases == ()
    assert spec.capability_bindings == {}
    assert spec.artifact_requirements == {}
    assert spec.gate_hooks == ()
    assert spec.budget_policy == {}
    assert spec.replan_policy == {}


def test_team_run_spec_with_roles() -> None:
    """roles must accept a tuple of AgentRole instances."""
    pi = _make_role("pi", "pi")
    survey = _make_role("survey", "survey")
    spec = TeamRunSpec(
        team_id="t", project_id="p", profile_id="prof", roles=(pi, survey)
    )
    assert len(spec.roles) == 2
    assert spec.roles[0].role_id == "pi"
    assert spec.roles[1].role_id == "survey"


def test_team_run_spec_with_phases() -> None:
    """phases must accept an ordered tuple of phase ID strings."""
    spec = TeamRunSpec(
        team_id="t",
        project_id="p",
        profile_id="prof",
        phases=("S1_plan", "S2_search", "S3_synthesize"),
    )
    assert spec.phases == ("S1_plan", "S2_search", "S3_synthesize")


def test_team_run_spec_with_capability_bindings() -> None:
    """capability_bindings maps phase_id → list of capability names."""
    bindings = {
        "S1_plan": ["llm_plan"],
        "S2_search": ["web_search", "document_reader"],
    }
    spec = TeamRunSpec(
        team_id="t", project_id="p", profile_id="prof", capability_bindings=bindings
    )
    assert spec.capability_bindings["S1_plan"] == ["llm_plan"]
    assert spec.capability_bindings["S2_search"] == ["web_search", "document_reader"]


def test_team_run_spec_with_artifact_requirements() -> None:
    """artifact_requirements maps phase_id → list of required artifact types."""
    reqs = {"S3_synthesize": ["ResearchArtifact", "EvidenceArtifact"]}
    spec = TeamRunSpec(
        team_id="t", project_id="p", profile_id="prof", artifact_requirements=reqs
    )
    assert spec.artifact_requirements["S3_synthesize"] == [
        "ResearchArtifact",
        "EvidenceArtifact",
    ]


def test_team_run_spec_with_gate_hooks() -> None:
    """gate_hooks must accept a tuple of gate type name strings."""
    spec = TeamRunSpec(
        team_id="t",
        project_id="p",
        profile_id="prof",
        gate_hooks=("ApprovalGate", "BudgetGate"),
    )
    assert spec.gate_hooks == ("ApprovalGate", "BudgetGate")


def test_team_run_spec_with_budget_policy() -> None:
    """budget_policy must accept arbitrary key/value pairs."""
    policy = {"max_cost_usd": 5.0, "max_tokens": 100_000}
    spec = TeamRunSpec(
        team_id="t", project_id="p", profile_id="prof", budget_policy=policy
    )
    assert spec.budget_policy["max_cost_usd"] == 5.0
    assert spec.budget_policy["max_tokens"] == 100_000


def test_team_run_spec_with_replan_policy() -> None:
    """replan_policy must accept arbitrary key/value pairs."""
    policy = {"allowed": True, "approval_required_after": 2}
    spec = TeamRunSpec(
        team_id="t", project_id="p", profile_id="prof", replan_policy=policy
    )
    assert spec.replan_policy["allowed"] is True
    assert spec.replan_policy["approval_required_after"] == 2


def test_team_run_spec_is_frozen() -> None:
    """TeamRunSpec must be a frozen dataclass (immutable after construction)."""
    import dataclasses

    spec = TeamRunSpec(team_id="t", project_id="p", profile_id="prof")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.team_id = "mutated"  # type: ignore[misc]  expiry_wave: Wave 17
