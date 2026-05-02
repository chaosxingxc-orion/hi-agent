"""Integration tests for RO-4: TeamRunRegistry SQLite-backed durable store.

Layer 2 — Integration: real TeamRunRegistry instances.
No mocks on the subsystem under test.
"""
from __future__ import annotations

import pytest
from hi_agent.contracts.team_runtime import TeamRun
from hi_agent.server.team_run_registry import TeamRunRegistry


@pytest.fixture()
def sample_team_run() -> TeamRun:
    return TeamRun(
        team_id="team-001",
        tenant_id="t-test",
        pi_run_id="run-pi-001",
        project_id="proj-001",
        member_runs=(("role-survey", "run-survey-001"), ("role-writer", "run-writer-001")),
        created_at="2026-04-25T00:00:00+00:00",
    )


class TestTeamRunRegistryDurability:
    """RO-4: verify that a file-backed registry persists data across registry instances."""

    def test_write_close_reopen_preserves_team_run(self, tmp_path, sample_team_run):
        """Write a team run, close the registry, reopen from the same file,
        verify the team run loads correctly."""
        db_file = str(tmp_path / "team_registry.sqlite")

        # First instance: write and close.
        reg1 = TeamRunRegistry(db_path=db_file)
        reg1.register(sample_team_run)
        reg1.close()

        # Second instance from same file: verify data persisted.
        reg2 = TeamRunRegistry(db_path=db_file)
        loaded = reg2.get("team-001")
        reg2.close()

        assert loaded is not None
        assert loaded.team_id == "team-001"
        assert loaded.lead_run_id == "run-pi-001"
        assert loaded.project_id == "proj-001"
        assert ("role-survey", "run-survey-001") in loaded.member_runs
        assert ("role-writer", "run-writer-001") in loaded.member_runs
        assert loaded.created_at == "2026-04-25T00:00:00+00:00"

    def test_register_replaces_existing_team(self, tmp_path):
        """Registering a team again with the same team_id replaces the old record."""
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)

        run_v1 = TeamRun(
            team_id="team-x", tenant_id="t-test", pi_run_id="run-v1", project_id="proj"
        )
        run_v2 = TeamRun(
            team_id="team-x", tenant_id="t-test", pi_run_id="run-v2", project_id="proj"
        )

        reg.register(run_v1)
        reg.register(run_v2)
        loaded = reg.get("team-x")
        reg.close()

        assert loaded is not None
        assert loaded.lead_run_id == "run-v2"

    def test_get_missing_team_returns_none(self, tmp_path):
        reg = TeamRunRegistry(db_path=str(tmp_path / "r.sqlite"))
        result = reg.get("no-such-team")
        reg.close()
        assert result is None

    def test_list_members_returns_member_pairs(self, tmp_path, sample_team_run):
        reg = TeamRunRegistry(db_path=str(tmp_path / "r.sqlite"))
        reg.register(sample_team_run)
        members = reg.list_members("team-001")
        reg.close()
        assert ("role-survey", "run-survey-001") in members
        assert ("role-writer", "run-writer-001") in members

    def test_list_members_unknown_team_returns_empty(self, tmp_path):
        reg = TeamRunRegistry(db_path=str(tmp_path / "r.sqlite"))
        members = reg.list_members("ghost-team")
        reg.close()
        assert members == []

    def test_unregister_removes_team(self, tmp_path, sample_team_run):
        reg = TeamRunRegistry(db_path=str(tmp_path / "r.sqlite"))
        reg.register(sample_team_run)
        reg.unregister("team-001")
        result = reg.get("team-001")
        reg.close()
        assert result is None

    def test_unregister_nonexistent_is_noop(self, tmp_path):
        """Unregistering a non-existent team_id must not raise."""
        reg = TeamRunRegistry(db_path=str(tmp_path / "r.sqlite"))
        reg.unregister("ghost-team")  # should not raise
        reg.close()

    def test_dev_posture_uses_memory(self, monkeypatch):
        """Under dev posture, db_path defaults to :memory:."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        reg = TeamRunRegistry()
        assert reg.db_path == ":memory:"
        reg.close()

    def test_research_posture_uses_file(self, monkeypatch, tmp_path):
        """Under research posture, db_path is file-backed."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
        reg = TeamRunRegistry()
        assert reg.db_path != ":memory:"
        assert "team_run_registry.sqlite" in reg.db_path
        reg.close()
