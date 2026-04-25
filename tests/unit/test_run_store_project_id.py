"""Unit tests: project_id first-class in RunRecord and SQLiteRunStore.

CO-4:
- RunRecord has project_id field (default empty string).
- SQLiteRunStore.upsert() persists project_id.
- SQLiteRunStore.get() restores project_id.
- SQLiteRunStore.list_runs_by_project() filters by tenant_id + project_id.
"""

from __future__ import annotations

import time

from hi_agent.server.run_store import RunRecord, SQLiteRunStore


def _make_record(run_id: str, tenant_id: str = "t1", project_id: str = "") -> RunRecord:
    now = time.time()
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
        created_at=now,
        updated_at=now,
        project_id=project_id,
    )


def test_run_record_has_project_id_field() -> None:
    """RunRecord dataclass must expose project_id with default empty string."""
    rec = _make_record("run-001")
    assert hasattr(rec, "project_id")
    assert rec.project_id == ""


def test_run_record_project_id_settable() -> None:
    """RunRecord.project_id must be settable at construction."""
    rec = _make_record("run-002", project_id="proj-abc")
    assert rec.project_id == "proj-abc"


def test_upsert_persists_project_id(tmp_path) -> None:
    """SQLiteRunStore.upsert() must write project_id to the database."""
    store = SQLiteRunStore(db_path=tmp_path / "runs.db")
    rec = _make_record("run-003", project_id="proj-123")
    store.upsert(rec)

    fetched = store.get("run-003")
    assert fetched is not None
    assert fetched.project_id == "proj-123"
    store.close()


def test_upsert_empty_project_id(tmp_path) -> None:
    """SQLiteRunStore.upsert() must persist empty project_id without error."""
    store = SQLiteRunStore(db_path=tmp_path / "runs.db")
    rec = _make_record("run-004", project_id="")
    store.upsert(rec)

    fetched = store.get("run-004")
    assert fetched is not None
    assert fetched.project_id == ""
    store.close()


def test_list_runs_by_project_returns_matching(tmp_path) -> None:
    """list_runs_by_project must return only runs with matching tenant + project."""
    store = SQLiteRunStore(db_path=tmp_path / "runs.db")
    store.upsert(_make_record("r1", tenant_id="t1", project_id="proj-a"))
    store.upsert(_make_record("r2", tenant_id="t1", project_id="proj-b"))
    store.upsert(_make_record("r3", tenant_id="t2", project_id="proj-a"))
    store.upsert(_make_record("r4", tenant_id="t1", project_id="proj-a"))

    results = store.list_runs_by_project("t1", "proj-a")
    run_ids = {r.run_id for r in results}
    assert run_ids == {"r1", "r4"}, f"Unexpected result set: {run_ids}"
    store.close()


def test_list_runs_by_project_empty_when_no_match(tmp_path) -> None:
    """list_runs_by_project must return empty list when no rows match."""
    store = SQLiteRunStore(db_path=tmp_path / "runs.db")
    store.upsert(_make_record("r1", tenant_id="t1", project_id="proj-a"))

    results = store.list_runs_by_project("t1", "proj-z")
    assert results == []
    store.close()


def test_migration_adds_project_id_column(tmp_path) -> None:
    """Opening an existing DB without project_id column must add it via _migrate()."""
    import sqlite3

    db_path = tmp_path / "old.db"
    # Create a database without the project_id column
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE run_records ("
        "run_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT '', "
        "user_id TEXT NOT NULL DEFAULT '__legacy__', "
        "session_id TEXT NOT NULL DEFAULT '__legacy__', "
        "task_contract_json TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'queued', "
        "priority INTEGER NOT NULL DEFAULT 5, "
        "attempt_count INTEGER NOT NULL DEFAULT 0, "
        "cancellation_flag INTEGER NOT NULL DEFAULT 0, "
        "result_summary TEXT NOT NULL DEFAULT '', "
        "error_summary TEXT NOT NULL DEFAULT '', "
        "created_at REAL NOT NULL DEFAULT 0, "
        "updated_at REAL NOT NULL DEFAULT 0)"
    )
    conn.commit()
    conn.close()

    # Opening with SQLiteRunStore should trigger migration
    store = SQLiteRunStore(db_path=db_path)
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(run_records)")}
    assert "project_id" in cols, f"project_id column not added by migration; cols: {cols}"
    store.close()
