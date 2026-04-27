"""DLQ restart-survival tests (IV-4).

Layer 2 (integration) — real file-backed SQLite RunQueue; zero mocks on
the subsystem under test.

Tests:
1. A dead-lettered run is still in the DLQ after RunQueue reconstruction.
2. attempts_count is preserved in the DLQ record after restart.
3. Auto-DLQ (via fail() exhausting max_attempts) produces a DLQ record
   that survives restart.
"""

from __future__ import annotations

from hi_agent.server.run_queue import RunQueue


def test_dead_lettered_run_survives_restart(tmp_path) -> None:
    """A run dead-lettered by q1 is visible in q2 (same DB file)."""
    db = str(tmp_path / "queue.db")

    q1 = RunQueue(db_path=db)
    q1.enqueue("dlq-restart-1", tenant_id="t1")
    q1.dead_letter(
        run_id="dlq-restart-1",
        reason="stuck_test",
        original_state="leased",
        tenant_id="t1",
    )

    # Restart: fresh instance, same DB.
    q2 = RunQueue(db_path=db)
    records = q2.list_dlq()
    run_ids = [r["run_id"] for r in records]
    assert "dlq-restart-1" in run_ids, "DLQ record lost after restart"


def test_attempts_count_in_dlq_record_after_restart(tmp_path) -> None:
    """attempts_count in DLQ record equals the attempt_count at dead-letter time."""
    db = str(tmp_path / "queue2.db")

    q1 = RunQueue(db_path=db, lease_timeout_seconds=1.0)
    q1.enqueue("dlq-attempts-1", tenant_id="t1")
    # Claim twice to bump attempt_count, then dead-letter.
    q1.claim_next("w1")
    q1.fail("dlq-attempts-1", "w1", "err1")   # attempt_count -> 1, re-queued
    q1.claim_next("w1")
    q1.fail("dlq-attempts-1", "w1", "err2")   # attempt_count -> 2 -> auto-DLQ (max=3 default)
    # Manually dead-letter at attempt 2 to capture a known count.
    # (auto-DLQ fires at max_attempts=3; use explicit dead_letter here)
    q1.dead_letter(
        run_id="dlq-attempts-1",
        reason="manual_test",
        original_state="failed",
        tenant_id="t1",
    )

    # Restart.
    q2 = RunQueue(db_path=db)
    records = q2.list_dlq(tenant_id="t1")
    assert len(records) == 1
    rec = records[0]
    assert rec["run_id"] == "dlq-attempts-1"
    # attempts_count should be >= 2 (the attempt_count at dead-letter time).
    assert rec["attempts_count"] >= 2, (
        f"Expected attempts_count >= 2, got {rec['attempts_count']}"
    )


def test_auto_dlq_via_fail_exhaustion_survives_restart(tmp_path) -> None:
    """A run auto-DLQ'd by fail() exhausting max_attempts survives restart."""
    db = str(tmp_path / "queue3.db")

    # Use max_attempts=2 for a shorter test.
    q1 = RunQueue(db_path=db)
    q1.enqueue("auto-dlq-1", tenant_id="t1")

    # Override max_attempts to 2 for this run.
    q1._conn.execute(
        "UPDATE run_queue SET max_attempts = 2 WHERE run_id = ?", ("auto-dlq-1",)
    )
    q1._conn.commit()

    # Exhaust attempts: fail twice.
    q1.claim_next("w1")
    q1.fail("auto-dlq-1", "w1", "err1")   # attempt 1 -> re-queued
    q1.claim_next("w1")
    q1.fail("auto-dlq-1", "w1", "err2")   # attempt 2 >= max_attempts -> auto-DLQ

    # Restart.
    q2 = RunQueue(db_path=db)
    dlq = q2.list_dlq()
    run_ids = [r["run_id"] for r in dlq]
    assert "auto-dlq-1" in run_ids, (
        "Auto-DLQ'd run not found in DLQ after restart"
    )
    rec = next(r for r in dlq if r["run_id"] == "auto-dlq-1")
    assert rec["reason"] == "max_attempts_exceeded"
    assert rec["attempts_count"] == 2
