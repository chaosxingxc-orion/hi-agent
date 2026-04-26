"""Unit test: SQLiteRunStore.upsert derives spine fields from exec_ctx."""
import time

from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.server.run_store import RunRecord, SQLiteRunStore


def _make_store(tmp_path):
    return SQLiteRunStore(db_path=str(tmp_path / "runs.db"))


def _make_record(
    run_id="r1",
    tenant_id="",
    user_id="__legacy__",
    session_id="__legacy__",
    project_id="",
):
    return RunRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        task_contract_json="{}",
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=time.time(),
        updated_at=time.time(),
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
    )


def test_upsert_derives_tenant_id_from_exec_ctx(tmp_path):
    """exec_ctx.tenant_id fills empty record.tenant_id."""
    store = _make_store(tmp_path)
    record = _make_record(run_id="r1", tenant_id="")
    ctx = RunExecutionContext(tenant_id="t-from-ctx", run_id="r1", project_id="p1")

    store.upsert(record, exec_ctx=ctx)

    retrieved = store.get("r1")
    assert retrieved is not None
    assert retrieved.tenant_id == "t-from-ctx"


def test_upsert_explicit_tenant_id_wins_over_exec_ctx(tmp_path):
    """Explicit record.tenant_id is not overwritten by exec_ctx."""
    store = _make_store(tmp_path)
    record = _make_record(run_id="r2", tenant_id="explicit-tenant")
    ctx = RunExecutionContext(tenant_id="ctx-tenant", run_id="r2")

    store.upsert(record, exec_ctx=ctx)

    retrieved = store.get("r2")
    assert retrieved is not None
    assert retrieved.tenant_id == "explicit-tenant"


def test_upsert_derives_project_id_from_exec_ctx(tmp_path):
    """exec_ctx.project_id fills empty record.project_id."""
    store = _make_store(tmp_path)
    record = _make_record(run_id="r3", tenant_id="t1", project_id="")
    ctx = RunExecutionContext(tenant_id="t1", run_id="r3", project_id="proj-from-ctx")

    store.upsert(record, exec_ctx=ctx)

    retrieved = store.get("r3")
    assert retrieved is not None
    assert retrieved.project_id == "proj-from-ctx"


def test_upsert_without_exec_ctx_unchanged(tmp_path):
    """Omitting exec_ctx leaves original behaviour intact."""
    store = _make_store(tmp_path)
    record = _make_record(run_id="r4", tenant_id="t1")

    store.upsert(record)

    retrieved = store.get("r4")
    assert retrieved is not None
    assert retrieved.tenant_id == "t1"
