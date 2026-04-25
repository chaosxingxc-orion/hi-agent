"""Track C: RunQueue spine columns."""
from hi_agent.server.run_queue import RunQueue


def test_enqueue_accepts_spine_fields(tmp_path):
    q = RunQueue(db_path=str(tmp_path / "q.sqlite"))
    q.enqueue("r1", priority=5, tenant_id="t1", user_id="u1", session_id="s1", project_id="p1")
    row = q._conn.execute(
        "SELECT tenant_id, user_id, session_id, project_id FROM run_queue WHERE run_id='r1'"
    ).fetchone()
    assert row == ("t1", "u1", "s1", "p1")


def test_dequeue_unclaimed(tmp_path):
    q = RunQueue(db_path=str(tmp_path / "q.sqlite"))
    q.enqueue("r1")
    q.dequeue_unclaimed("r1")
    row = q._conn.execute("SELECT * FROM run_queue WHERE run_id='r1'").fetchone()
    assert row is None


def test_spine_columns_in_schema(tmp_path):
    q = RunQueue(db_path=str(tmp_path / "q.sqlite"))
    cols = {row[1] for row in q._conn.execute("PRAGMA table_info(run_queue)")}
    for col in ("tenant_id", "user_id", "session_id", "project_id"):
        assert col in cols, f"{col} missing from run_queue schema"


def test_dequeue_unclaimed_noop_when_claimed(tmp_path):
    q = RunQueue(db_path=str(tmp_path / "q.sqlite"))
    q.enqueue("r2")
    # Claim it first.
    q.claim_next("worker-1")
    # dequeue_unclaimed should NOT remove a leased row.
    q.dequeue_unclaimed("r2")
    row = q._conn.execute("SELECT status FROM run_queue WHERE run_id='r2'").fetchone()
    assert row is not None
    assert row[0] == "leased"
