"""Integration: team run member registration and lineage tracking (P4.3)."""

from __future__ import annotations

from hi_agent.contracts.team_runtime import TeamRun
from hi_agent.server.team_run_registry import TeamRunRegistry


def test_register_and_retrieve_team():
    """register() stores a TeamRun; get() returns it with correct pi_run_id."""
    registry = TeamRunRegistry()
    team = TeamRun(
        team_id="t1",
        pi_run_id="run-pi",
        project_id="proj-1",
        member_runs=(("pi", "run-pi"), ("survey", "run-survey")),
    )
    registry.register(team)
    retrieved = registry.get("t1")
    assert retrieved is not None
    assert retrieved.pi_run_id == "run-pi"


def test_list_members_returns_all_pairs():
    """list_members() returns the full (role_id, run_id) list."""
    registry = TeamRunRegistry()
    team = TeamRun(
        team_id="t2",
        pi_run_id="run-pi-2",
        project_id="proj-2",
        member_runs=(("pi", "run-pi-2"), ("survey", "run-survey-2")),
    )
    registry.register(team)
    members = registry.list_members("t2")
    assert len(members) == 2
    assert ("pi", "run-pi-2") in members
    assert ("survey", "run-survey-2") in members


def test_get_unknown_team_returns_none():
    """get() returns None for an unregistered team_id."""
    registry = TeamRunRegistry()
    assert registry.get("nonexistent") is None


def test_list_members_unknown_team_returns_empty():
    """list_members() returns [] for an unregistered team_id."""
    registry = TeamRunRegistry()
    assert registry.list_members("nonexistent") == []


def test_register_replaces_existing():
    """Registering a second TeamRun with the same team_id replaces the first."""
    registry = TeamRunRegistry()
    team_v1 = TeamRun(team_id="t3", pi_run_id="run-pi-v1", project_id="proj-3")
    team_v2 = TeamRun(
        team_id="t3",
        pi_run_id="run-pi-v2",
        project_id="proj-3",
        member_runs=(("pi", "run-pi-v2"),),
    )
    registry.register(team_v1)
    registry.register(team_v2)
    assert registry.get("t3").pi_run_id == "run-pi-v2"  # type: ignore[union-attr]  expiry_wave: Wave 17


def test_unregister_removes_team():
    """unregister() removes the team; subsequent get() returns None."""
    registry = TeamRunRegistry()
    team = TeamRun(team_id="t4", pi_run_id="run-pi-4", project_id="proj-4")
    registry.register(team)
    registry.unregister("t4")
    assert registry.get("t4") is None
