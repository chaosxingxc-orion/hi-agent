"""Unit tests for TeamRunRegistry.register with exec_ctx.

Layer 1 — Unit tests; SQLite in-memory (no external mocks).
"""

from __future__ import annotations

import pytest
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.contracts.team_runtime import TeamRun
from hi_agent.server.team_run_registry import TeamRunRegistry


@pytest.fixture()
def registry():
    """Fresh in-memory TeamRunRegistry."""
    r = TeamRunRegistry(db_path=":memory:")
    yield r
    r.close()


def _make_team_run(**kwargs) -> TeamRun:
    defaults: dict = {
        "team_id": "team-001",
        "pi_run_id": "pi-run-001",
        "project_id": "proj-001",
        "tenant_id": "test-tenant",
        "member_runs": (),
    }
    defaults.update(kwargs)
    return TeamRun(**defaults)


class TestRegisterWithExecCtx:
    def test_exec_ctx_spine_stored_in_team_run(self, registry):
        """exec_ctx tenant/user/session fields are persisted in the registry."""
        ctx = RunExecutionContext(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            project_id="p1",
        )
        team_run = _make_team_run(team_id="team-ctx-001")
        registry.register(team_run, exec_ctx=ctx)

        retrieved = registry.get("team-ctx-001")
        assert retrieved is not None
        assert retrieved.tenant_id == "t1"
        assert retrieved.user_id == "u1"
        assert retrieved.session_id == "s1"

    def test_exec_ctx_none_uses_team_run_fields(self, registry):
        """When exec_ctx is None, TeamRun's own spine fields are stored."""
        team_run = _make_team_run(
            team_id="team-no-ctx",
            tenant_id="t-original",
            user_id="u-original",
            session_id="s-original",
        )
        registry.register(team_run, exec_ctx=None)

        retrieved = registry.get("team-no-ctx")
        assert retrieved is not None
        assert retrieved.tenant_id == "t-original"
        assert retrieved.user_id == "u-original"
        assert retrieved.session_id == "s-original"

    def test_exec_ctx_empty_fields_fall_back_to_team_run_spine(self, registry):
        """exec_ctx empty fields do not overwrite non-empty TeamRun spine fields."""
        ctx = RunExecutionContext(
            tenant_id="",   # empty
            user_id="u-ctx",
            session_id="",  # empty
        )
        team_run = _make_team_run(
            team_id="team-partial",
            tenant_id="t-teamrun",
            user_id="u-teamrun",
            session_id="s-teamrun",
        )
        registry.register(team_run, exec_ctx=ctx)

        retrieved = registry.get("team-partial")
        assert retrieved is not None
        # empty ctx fields → TeamRun fields win
        assert retrieved.tenant_id == "t-teamrun"
        # non-empty ctx field → ctx wins
        assert retrieved.user_id == "u-ctx"
        assert retrieved.session_id == "s-teamrun"

    def test_register_without_exec_ctx_backward_compat(self, registry):
        """Existing callers that don't pass exec_ctx continue to work."""
        team_run = _make_team_run(team_id="team-compat")
        registry.register(team_run)  # no exec_ctx kwarg

        retrieved = registry.get("team-compat")
        assert retrieved is not None
        assert retrieved.team_id == "team-compat"
