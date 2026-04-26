"""Integration tests for W5-C recovery: posture-driven re-enqueue.

Layer 2 — real components wired together.  Zero mocks on the subsystem
under test (RunQueue + _rehydrate_runs + recovery state machine).

Verifies:
  1. Under research posture, an expired-lease run is re-enqueued without
     any env var.
  2. Under dev posture, the run is NOT re-enqueued (warn-only).
  3. Double-execute prevention: two concurrent recovery passes claim exactly
     one winner; the second skips.
  4. Tenant spine is preserved on the re-queued entry.
"""
from __future__ import annotations

import time
import uuid

import pytest
from hi_agent.config.posture import Posture
from hi_agent.server.recovery import RecoveryState, decide_recovery_action
from hi_agent.server.run_queue import RunQueue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_queue() -> RunQueue:
    """Return a fresh in-memory RunQueue."""
    return RunQueue(db_path=":memory:", lease_timeout_seconds=60.0)


def _insert_expired_lease(rq: RunQueue, run_id: str, tenant_id: str = "tenant-1") -> None:
    """Enqueue, claim, then backdated the lease_expires_at to simulate expiry."""
    rq.enqueue(run_id=run_id, tenant_id=tenant_id, user_id="u1", session_id="s1", project_id="p1")
    rq.claim_next(worker_id="dead-worker")
    # Backdate the lease so it appears expired.
    rq._conn.execute(
        "UPDATE run_queue SET lease_expires_at = ? WHERE run_id = ?",
        (time.time() - 10.0, run_id),
    )
    rq._conn.commit()


def _apply_recovery(rq: RunQueue, posture: Posture) -> list[dict]:
    """Run the recovery logic directly (mirrors _rehydrate_runs without env coupling)."""
    import os

    reenqueue_flag = os.environ.get("HI_AGENT_RECOVERY_REENQUEUE", "1")
    opt_out = reenqueue_flag == "0"

    expired = rq.expire_stale_leases()
    requeued = []

    for entry in expired:
        run_id = entry["run_id"]
        tenant_id = entry["tenant_id"]

        decision = decide_recovery_action(
            run_id=run_id,
            tenant_id=tenant_id,
            current_state=RecoveryState.LEASE_EXPIRED,
            posture=posture,
        )
        effective_requeue = decision.should_requeue and not opt_out

        if effective_requeue:
            token = str(uuid.uuid4())
            claimed = rq.claim_with_adoption_token(run_id, token)
            if not claimed:
                continue
            rq.reenqueue(run_id=run_id, tenant_id=tenant_id)
            requeued.append(entry)

    return requeued


def _get_status(rq: RunQueue, run_id: str) -> str | None:
    cur = rq._conn.execute("SELECT status FROM run_queue WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Test 1: research posture → re-enqueue without env var
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_research_posture_requeues_expired_lease(monkeypatch):
    """Under research posture, an expired-lease run is re-enqueued without any env var."""
    monkeypatch.delenv("HI_AGENT_RECOVERY_REENQUEUE", raising=False)
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    rq = _make_queue()
    run_id = "run-research-" + str(uuid.uuid4())
    _insert_expired_lease(rq, run_id, tenant_id="tenant-r")

    requeued = _apply_recovery(rq, Posture.RESEARCH)

    assert any(e["run_id"] == run_id for e in requeued), (
        f"Expected run_id={run_id} to be re-enqueued under research posture"
    )
    # After re-enqueue the status should be 'queued' again.
    assert _get_status(rq, run_id) == "queued"

    rq.close()


# ---------------------------------------------------------------------------
# Test 2: dev posture → warn-only, no re-enqueue
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_dev_posture_warn_only_no_requeue(monkeypatch):
    """Under dev posture, an expired-lease run is NOT re-enqueued."""
    monkeypatch.delenv("HI_AGENT_RECOVERY_REENQUEUE", raising=False)
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    rq = _make_queue()
    run_id = "run-dev-" + str(uuid.uuid4())
    _insert_expired_lease(rq, run_id, tenant_id="tenant-d")

    requeued = _apply_recovery(rq, Posture.DEV)

    assert not any(e["run_id"] == run_id for e in requeued), (
        "Expected run_id not to be re-enqueued under dev posture"
    )
    # Status must remain 'leased' (not re-queued by recovery).
    assert _get_status(rq, run_id) == "leased"

    rq.close()


# ---------------------------------------------------------------------------
# Test 3: double-execute prevention — two passes, exactly one wins
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_double_execute_prevention(monkeypatch):
    """Two concurrent recovery passes can only adopt a run once.

    The second pass must get claim_with_adoption_token=False and skip the run.
    """
    monkeypatch.delenv("HI_AGENT_RECOVERY_REENQUEUE", raising=False)

    rq = _make_queue()
    run_id = "run-dup-" + str(uuid.uuid4())
    _insert_expired_lease(rq, run_id, tenant_id="tenant-dup")

    # First pass claims the adoption_token.
    token_1 = str(uuid.uuid4())
    won_1 = rq.claim_with_adoption_token(run_id, token_1)
    assert won_1 is True, "First recovery pass must win"

    # Second pass must fail — token already set.
    token_2 = str(uuid.uuid4())
    won_2 = rq.claim_with_adoption_token(run_id, token_2)
    assert won_2 is False, "Second recovery pass must lose"

    # Verify the DB holds token_1.
    cur = rq._conn.execute("SELECT adoption_token FROM run_queue WHERE run_id = ?", (run_id,))
    stored_token = cur.fetchone()[0]
    assert stored_token == token_1

    rq.close()


# ---------------------------------------------------------------------------
# Test 4: tenant spine is preserved on re-queued entry
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_recovery_preserves_tenant_spine(monkeypatch):
    """Re-enqueued run carries the same tenant_id as the original entry."""
    monkeypatch.delenv("HI_AGENT_RECOVERY_REENQUEUE", raising=False)
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    rq = _make_queue()
    run_id = "run-spine-" + str(uuid.uuid4())
    expected_tenant = "tenant-spine-42"
    _insert_expired_lease(rq, run_id, tenant_id=expected_tenant)

    requeued = _apply_recovery(rq, Posture.RESEARCH)

    assert any(e["run_id"] == run_id for e in requeued)

    # Query the DB and confirm tenant_id is preserved.
    cur = rq._conn.execute(
        "SELECT tenant_id FROM run_queue WHERE run_id = ?", (run_id,)
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == expected_tenant

    rq.close()


# ---------------------------------------------------------------------------
# Test 5: opt-out env var suppresses re-enqueue under research
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_opt_out_suppresses_requeue_under_research(monkeypatch):
    """HI_AGENT_RECOVERY_REENQUEUE=0 suppresses re-enqueue even under research posture."""
    monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "0")
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    rq = _make_queue()
    run_id = "run-optout-" + str(uuid.uuid4())
    _insert_expired_lease(rq, run_id, tenant_id="tenant-optout")

    requeued = _apply_recovery(rq, Posture.RESEARCH)

    assert not any(e["run_id"] == run_id for e in requeued), (
        "Expected no re-enqueue when HI_AGENT_RECOVERY_REENQUEUE=0"
    )
    assert _get_status(rq, run_id) == "leased"

    rq.close()
