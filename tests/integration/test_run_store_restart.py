"""Durable run store restart-survival tests (IV-4).

Layer 2 (integration) — real file-backed SQLite; zero mocks on the
subsystem under test.

Tests:
1. A run upserted in one SQLiteRunStore instance is readable in a fresh
   instance pointing to the same DB file.
2. list_pending() returns in-flight runs after restart (restart-recovery path).
3. Terminal status changes survive restart.
"""

from __future__ import annotations

import time
import uuid

from hi_agent.server.run_store import RunRecord, SQLiteRunStore


def _make_record(run_id: str | None = None, tenant_id: str = "t1") -> RunRecord:
    now = time.time()
    return RunRecord(
        run_id=run_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id="u1",
        session_id="s1",
        task_contract_json='{"task":"probe"}',
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=now,
        updated_at=now,
    )


def test_run_record_visible_after_store_restart(tmp_path) -> None:
    """A run written by store1 is readable by store2 (same DB file)."""
    db = str(tmp_path / "runs.db")
    rec = _make_record()

    store1 = SQLiteRunStore(db_path=db)
    store1.upsert(rec)

    store2 = SQLiteRunStore(db_path=db)
    recovered = store2.get(rec.run_id)
    assert recovered is not None, "Run record lost after restart"
    assert recovered.run_id == rec.run_id
    assert recovered.tenant_id == "t1"
    assert recovered.status == "queued"


def test_list_pending_returns_in_flight_runs_after_restart(tmp_path) -> None:
    """Runs in 'queued' or 'running' status appear in list_pending() after restart."""
    db = str(tmp_path / "runs2.db")

    store1 = SQLiteRunStore(db_path=db)
    queued_rec = _make_record()
    running_rec = _make_record()

    store1.upsert(queued_rec)
    store1.upsert(running_rec)
    store1.mark_running(running_rec.run_id)

    # Restart.
    store2 = SQLiteRunStore(db_path=db)
    pending = store2.list_pending()
    pending_ids = {r.run_id for r in pending}

    assert queued_rec.run_id in pending_ids, "Queued run lost after restart"
    assert running_rec.run_id in pending_ids, "Running run lost after restart"


def test_terminal_status_persists_after_restart(tmp_path) -> None:
    """mark_complete / mark_failed / mark_cancelled survive restart."""
    db = str(tmp_path / "runs3.db")

    store1 = SQLiteRunStore(db_path=db)
    completed_rec = _make_record()
    failed_rec = _make_record()
    cancelled_rec = _make_record()

    for rec in (completed_rec, failed_rec, cancelled_rec):
        store1.upsert(rec)

    store1.mark_complete(completed_rec.run_id, "result_ok")
    store1.mark_failed(failed_rec.run_id, "oops")
    store1.mark_cancelled(cancelled_rec.run_id)

    # Restart.
    store2 = SQLiteRunStore(db_path=db)
    assert store2.get(completed_rec.run_id).status == "completed"
    assert store2.get(failed_rec.run_id).status == "failed"
    assert store2.get(cancelled_rec.run_id).status == "cancelled"
