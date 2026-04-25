"""Track C: RunStore terminal state sync — mark_* methods set finished_at."""
import time
from hi_agent.server.run_store import SQLiteRunStore, RunRecord


def _make_store(tmp_path):
    return SQLiteRunStore(db_path=str(tmp_path / "runs.db"))


def _make_record(run_id="r1"):
    return RunRecord(
        run_id=run_id, tenant_id="t1", task_contract_json="{}", status="queued",
        priority=5, attempt_count=0, cancellation_flag=False,
        result_summary="", error_summary="", created_at=time.time(), updated_at=time.time(),
        user_id="u1", session_id="s1", project_id="p1",
    )


def test_mark_complete_sets_finished_at(tmp_path):
    store = _make_store(tmp_path)
    store.upsert(_make_record())
    before = time.time()
    store.mark_complete("r1", "ok")
    rec = store.get("r1")
    assert rec.status == "completed"
    assert rec.finished_at >= before


def test_mark_failed_sets_finished_at(tmp_path):
    store = _make_store(tmp_path)
    store.upsert(_make_record())
    store.mark_failed("r1", "err")
    rec = store.get("r1")
    assert rec.status == "failed"
    assert rec.finished_at > 0


def test_mark_cancelled_sets_finished_at(tmp_path):
    store = _make_store(tmp_path)
    store.upsert(_make_record())
    store.mark_cancelled("r1")
    rec = store.get("r1")
    assert rec.status == "cancelled"
    assert rec.finished_at > 0


def test_list_by_workspace_includes_project_id(tmp_path):
    store = _make_store(tmp_path)
    r = _make_record()
    r.project_id = "proj-abc"
    store.upsert(r)
    records = store.list_by_workspace("t1", "u1", "s1")
    assert records[0].project_id == "proj-abc"


def test_mark_running_sets_status(tmp_path):
    store = _make_store(tmp_path)
    store.upsert(_make_record())
    store.mark_running("r1")
    rec = store.get("r1")
    assert rec.status == "running"


def test_delete_removes_record(tmp_path):
    store = _make_store(tmp_path)
    store.upsert(_make_record())
    store.delete("r1")
    assert store.get("r1") is None


def test_finished_at_zero_on_fresh_record(tmp_path):
    store = _make_store(tmp_path)
    store.upsert(_make_record())
    rec = store.get("r1")
    assert rec.finished_at == 0.0
