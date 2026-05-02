"""Integration tests for Track Spine-2: TeamRun contract spine persistence.

Rule 12 — Contract Spine Completeness: every persistent record must carry
``tenant_id`` plus the relevant subset of ``user_id`` / ``session_id``.

Layer 2 — Integration: real SQLite-backed TeamRunRegistry on a temp dir.
No mocks on the subsystem under test.  Spine values are asserted by querying
SQLite directly to prove the bytes hit the row, not by trusting the
``_from_row`` round-trip alone.
"""
from __future__ import annotations

import sqlite3

import pytest
from hi_agent.contracts.team_runtime import TeamRun
from hi_agent.server.team_run_registry import TeamRunRegistry

pytestmark = pytest.mark.integration


def _make_team_run(**overrides) -> TeamRun:
    base = {
        "team_id": "team-spine-1",
        "pi_run_id": "run-pi-spine-1",
        "project_id": "proj-spine-1",
        "member_runs": (("role-survey", "run-survey-1"),),
        "created_at": "2026-04-26T00:00:00+00:00",
        "tenant_id": "t-a",
        "user_id": "u-a",
        "session_id": "s-a",
    }
    base.update(overrides)
    return TeamRun(**base)


class TestTeamRunRegisterPersistsSpine:
    """register() writes tenant_id/user_id/session_id into the SQLite row."""

    def test_team_run_register_persists_spine_columns(self, tmp_path):
        """SQLite row must carry the exact spine values supplied to register()."""
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        team = _make_team_run(
            team_id="team-spine-A",
            tenant_id="t-a",
            user_id="u-a",
            session_id="s-a",
        )
        reg.register(team)
        reg.close()

        # Direct sqlite3 query — bypasses _from_row to prove bytes hit the row.
        conn = sqlite3.connect(db_file)
        try:
            cur = conn.execute(
                "SELECT tenant_id, user_id, session_id FROM team_runs WHERE team_id = ?",
                ("team-spine-A",),
            )
            row = cur.fetchone()
        finally:
            conn.close()

        assert row is not None, "row was not inserted"
        assert row[0] == "t-a", f"tenant_id: expected 't-a', got {row[0]!r}"
        assert row[1] == "u-a", f"user_id: expected 'u-a', got {row[1]!r}"
        assert row[2] == "s-a", f"session_id: expected 's-a', got {row[2]!r}"

    def test_team_run_register_persists_distinct_tenants(self, tmp_path):
        """Two TeamRuns with different tenant_id values must both persist correctly."""
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        reg.register(
            _make_team_run(team_id="team-A", tenant_id="t-a", user_id="u-a", session_id="s-a")
        )
        reg.register(
            _make_team_run(team_id="team-B", tenant_id="t-b", user_id="u-b", session_id="s-b")
        )
        reg.close()

        conn = sqlite3.connect(db_file)
        try:
            rows = dict(
                conn.execute(
                    "SELECT team_id, tenant_id FROM team_runs ORDER BY team_id"
                ).fetchall()
            )
        finally:
            conn.close()

        assert rows == {"team-A": "t-a", "team-B": "t-b"}


class TestTeamRunGetReturnsSpine:
    """get() round-trips spine values into the TeamRun dataclass."""

    def test_team_run_get_returns_spine(self, tmp_path):
        """register -> get must surface tenant/user/session on the TeamRun instance."""
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        original = _make_team_run(
            team_id="team-rt",
            tenant_id="t-rt",
            user_id="u-rt",
            session_id="s-rt",
        )
        reg.register(original)
        loaded = reg.get("team-rt")
        reg.close()

        assert loaded is not None
        assert loaded.team_id == "team-rt"
        assert loaded.tenant_id == "t-rt"
        assert loaded.user_id == "u-rt"
        assert loaded.session_id == "s-rt"
        # And spine round-trips alongside the original payload fields.
        assert loaded.lead_run_id == "run-pi-spine-1"
        assert loaded.project_id == original.project_id
        assert loaded.member_runs == original.member_runs
        assert loaded.created_at == original.created_at


class TestTeamRunRegisterPostureAware:
    """Posture-aware default behaviour (Rule 11): research/prod fail-closed.

    Under research/prod posture an empty tenant_id at register() time is a
    hard error — Rule 12 requires every persistent record to answer "which
    tenant".  Under dev posture an empty tenant_id is permitted (warn-only
    via test honesty: the test asserts the dev branch does not raise).
    """

    def test_team_run_register_default_empty_spine_under_research_posture_raises(
        self, tmp_path, monkeypatch
    ):
        """research posture + empty tenant_id must raise ValueError, not silently default."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        team = TeamRun(
            team_id="team-empty",
            pi_run_id="run-pi-empty",
            project_id="proj-empty",
            # tenant_id deliberately omitted — defaults to ""
        )
        with pytest.raises(ValueError, match="tenant_id is required"):
            reg.register(team)
        reg.close()

    def test_team_run_register_empty_spine_under_dev_posture_allows(
        self, tmp_path, monkeypatch
    ):
        """dev posture must remain permissive for backward-compatible callers."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        team = TeamRun(
            team_id="team-dev",
            pi_run_id="run-pi-dev",
            project_id="proj-dev",
        )
        reg.register(team)  # must not raise
        loaded = reg.get("team-dev")
        reg.close()
        assert loaded is not None
        assert loaded.tenant_id == ""

    def test_team_run_register_with_spine_under_research_posture_succeeds(
        self, tmp_path, monkeypatch
    ):
        """research posture + non-empty tenant_id must persist normally."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        team = _make_team_run(
            team_id="team-strict",
            tenant_id="t-strict",
            user_id="u-strict",
            session_id="s-strict",
        )
        reg.register(team)
        reg.close()

        conn = sqlite3.connect(db_file)
        try:
            row = conn.execute(
                "SELECT tenant_id FROM team_runs WHERE team_id = ?",
                ("team-strict",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and row[0] == "t-strict"
