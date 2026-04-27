"""Durable idempotency store restart-survival tests (IV-4).

Layer 2 (integration) — real file-backed SQLite; zero mocks on the
subsystem under test.

Tests:
1. An idempotency key written in one instance is readable in a fresh instance
   (replay returns the same run_id, not a new one).
2. A completed idempotency record survives restart and is replayed correctly.
"""

from __future__ import annotations

import uuid

from hi_agent.server.idempotency import IdempotencyStore, _hash_payload


def test_idempotency_key_readable_after_restart(tmp_path) -> None:
    """A key reserved in instance s1 replays from instance s2 (same DB file)."""
    db = str(tmp_path / "idem.db")
    tenant_id = "t-restart"
    key = "key-" + str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    payload = {"task": "idempotency_restart_probe"}
    request_hash = _hash_payload(payload)

    s1 = IdempotencyStore(db_path=db)
    outcome1, rec1 = s1.reserve_or_replay(
        tenant_id=tenant_id,
        idempotency_key=key,
        request_hash=request_hash,
        run_id=run_id,
    )
    assert outcome1 == "created"
    assert rec1.run_id == run_id

    # Restart: fresh instance, same DB file.
    s2 = IdempotencyStore(db_path=db)
    outcome2, rec2 = s2.reserve_or_replay(
        tenant_id=tenant_id,
        idempotency_key=key,
        request_hash=request_hash,
        run_id=str(uuid.uuid4()),  # different candidate; should be ignored
    )
    assert outcome2 == "replayed", f"Expected 'replayed', got '{outcome2}'"
    assert rec2.run_id == run_id, (
        f"Replayed run_id mismatch: expected {run_id}, got {rec2.run_id}"
    )


def test_completed_idempotency_record_survives_restart(tmp_path) -> None:
    """A mark_complete'd record is still present and replayed after restart."""
    db = str(tmp_path / "idem2.db")
    tenant_id = "t-complete"
    key = "key-" + str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    payload = {"task": "complete_restart_probe"}
    request_hash = _hash_payload(payload)
    response_snap = '{"state": "completed"}'

    s1 = IdempotencyStore(db_path=db)
    s1.reserve_or_replay(
        tenant_id=tenant_id,
        idempotency_key=key,
        request_hash=request_hash,
        run_id=run_id,
    )
    s1.mark_complete(
        tenant_id=tenant_id,
        idempotency_key=key,
        response_json=response_snap,
        terminal_state="succeeded",
    )

    # Restart.
    s2 = IdempotencyStore(db_path=db)
    outcome, rec = s2.reserve_or_replay(
        tenant_id=tenant_id,
        idempotency_key=key,
        request_hash=request_hash,
        run_id=str(uuid.uuid4()),
    )
    assert outcome == "replayed", f"Expected 'replayed' after restart, got '{outcome}'"
    assert rec.run_id == run_id
    assert rec.response_snapshot == response_snap
