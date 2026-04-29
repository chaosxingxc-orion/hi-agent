"""Track C: TeamRunRegistry status + finished_at columns."""
import time

from hi_agent.contracts.team_runtime import TeamRun
from hi_agent.server.team_run_registry import TeamRunRegistry


def _make_team_run():
    return TeamRun(
        team_id="t1", pi_run_id="r1", project_id="p1", tenant_id="test-tenant",
        member_runs=(), created_at="now",
    )


def test_set_status_updates_db(tmp_path):
    reg = TeamRunRegistry(db_path=str(tmp_path / "reg.sqlite"))
    reg.register(_make_team_run())
    reg.set_status("t1", "running")
    row = reg._conn.execute("SELECT status FROM team_runs WHERE team_id='t1'").fetchone()
    assert row[0] == "running"


def test_set_status_completed_sets_finished_at(tmp_path):
    reg = TeamRunRegistry(db_path=str(tmp_path / "reg.sqlite"))
    reg.register(_make_team_run())
    before = time.time()
    reg.set_status("t1", "completed")
    row = reg._conn.execute(
        "SELECT status, finished_at FROM team_runs WHERE team_id='t1'"
    ).fetchone()
    assert row[0] == "completed"
    assert row[1] >= before


def test_schema_has_status_and_finished_at(tmp_path):
    reg = TeamRunRegistry(db_path=str(tmp_path / "reg.sqlite"))
    cols = {row[1] for row in reg._conn.execute("PRAGMA table_info(team_runs)")}
    assert "status" in cols
    assert "finished_at" in cols


def test_set_status_running_finished_at_zero(tmp_path):
    reg = TeamRunRegistry(db_path=str(tmp_path / "reg.sqlite"))
    reg.register(_make_team_run())
    reg.set_status("t1", "running")
    row = reg._conn.execute("SELECT finished_at FROM team_runs WHERE team_id='t1'").fetchone()
    assert row[0] == 0.0


def test_feedback_store_spine_fields():
    import dataclasses

    from hi_agent.evolve.feedback_store import RunFeedback
    fields = {f.name for f in dataclasses.fields(RunFeedback)}
    for spine in ("tenant_id", "user_id", "session_id", "project_id"):
        assert spine in fields, f"RunFeedback missing spine field: {spine}"
