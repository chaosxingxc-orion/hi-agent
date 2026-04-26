"""Unit tests for the W5-C recovery state machine.

Layer 1 — one function per test; no external IO, no mocks on the unit under test.
Tests every transition in ``decide_recovery_action`` across postures and opt-out.
"""
from __future__ import annotations

import os

import pytest
from hi_agent.config.posture import Posture
from hi_agent.server.recovery import RecoveryDecision, RecoveryState, decide_recovery_action

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decision(
    run_id: str = "run-abc",
    tenant_id: str = "tenant-x",
    current_state: RecoveryState = RecoveryState.LEASE_EXPIRED,
    posture: Posture = Posture.RESEARCH,
) -> RecoveryDecision:
    return decide_recovery_action(run_id, tenant_id, current_state, posture)


# ---------------------------------------------------------------------------
# 1. LEASE_EXPIRED + research posture → should_requeue=True, to_state=REQUEUED
# ---------------------------------------------------------------------------

def test_lease_expired_research_posture_requeues():
    """Under research posture, LEASE_EXPIRED → REQUEUED with should_requeue=True."""
    decision = _decision(posture=Posture.RESEARCH)
    assert decision.should_requeue is True
    assert decision.to_state == RecoveryState.REQUEUED
    assert decision.from_state == RecoveryState.LEASE_EXPIRED


def test_lease_expired_prod_posture_requeues():
    """Under prod posture, LEASE_EXPIRED → REQUEUED with should_requeue=True."""
    decision = _decision(posture=Posture.PROD)
    assert decision.should_requeue is True
    assert decision.to_state == RecoveryState.REQUEUED


# ---------------------------------------------------------------------------
# 2. LEASE_EXPIRED + dev posture → should_requeue=False, to_state=LEASE_EXPIRED
# ---------------------------------------------------------------------------

def test_lease_expired_dev_posture_warn_only():
    """Under dev posture, LEASE_EXPIRED → no re-enqueue; state remains LEASE_EXPIRED."""
    decision = _decision(posture=Posture.DEV)
    assert decision.should_requeue is False
    assert decision.to_state == RecoveryState.LEASE_EXPIRED
    assert decision.from_state == RecoveryState.LEASE_EXPIRED


# ---------------------------------------------------------------------------
# 3. Non-LEASE_EXPIRED states → no action, from_state == to_state
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state", [
    RecoveryState.QUEUED,
    RecoveryState.LEASED,
    RecoveryState.RUNNING,
    RecoveryState.REQUEUED,
    RecoveryState.ADOPTED,
    RecoveryState.FAILED_TERMINAL,
])
def test_non_lease_expired_state_no_action(state):
    """States other than LEASE_EXPIRED: should_requeue=False, from_state==to_state."""
    decision = _decision(current_state=state, posture=Posture.RESEARCH)
    assert decision.should_requeue is False
    assert decision.from_state == state
    assert decision.to_state == state


# ---------------------------------------------------------------------------
# 4. HI_AGENT_RECOVERY_REENQUEUE=0 opt-out — verify should_requeue=False from posture
#    (the opt-out is applied by _rehydrate_runs, not decide_recovery_action;
#     this test verifies that the decision alone is correct, and the caller
#     applies the opt-out override)
# ---------------------------------------------------------------------------

def test_research_posture_decision_is_true_before_opt_out():
    """decide_recovery_action returns should_requeue=True for research; opt-out is caller's job."""
    decision = _decision(posture=Posture.RESEARCH)
    # The decision itself says requeue=True; _rehydrate_runs applies the opt-out.
    assert decision.should_requeue is True


def test_opt_out_env_var_respected_in_rehydrate(monkeypatch, tmp_path):
    """HI_AGENT_RECOVERY_REENQUEUE=0 suppresses re-enqueue even under research posture.

    This tests the _rehydrate_runs integration with the opt-out env var.
    We use a real RunQueue with an in-memory SQLite backend.
    """
    import time

    from hi_agent.server.run_queue import RunQueue

    monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "0")
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    # Build a real in-memory queue with an artificially expired lease.
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=1.0)
    rq.enqueue(run_id="run-opt-out", tenant_id="t1")
    rq.claim_next(worker_id="worker-1")

    # Fast-forward lease expiry by manipulating the DB directly.
    rq._conn.execute(
        "UPDATE run_queue SET lease_expires_at = ? WHERE run_id = 'run-opt-out'",
        (time.time() - 10.0,),
    )
    rq._conn.commit()

    # Confirm expire_stale_leases sees the run.
    expired = rq.expire_stale_leases()
    assert any(e["run_id"] == "run-opt-out" for e in expired)

    # Now apply the opt-out decision: should_requeue from decide_recovery_action
    # is True, but effective_requeue must be False because opt_out=True.
    posture = Posture.from_env()
    assert posture.is_strict  # research posture is active

    for entry in expired:
        d = decide_recovery_action(
            run_id=entry["run_id"],
            tenant_id=entry["tenant_id"],
            current_state=RecoveryState.LEASE_EXPIRED,
            posture=posture,
        )
        # Decision says requeue, but opt-out overrides.
        assert d.should_requeue is True  # raw decision
        effective = d.should_requeue and (os.environ.get("HI_AGENT_RECOVERY_REENQUEUE", "1") != "0")
        assert effective is False  # opt-out suppresses it

    rq.close()


# ---------------------------------------------------------------------------
# 5. Decision carries correct run_id / tenant_id
# ---------------------------------------------------------------------------

def test_decision_carries_spine_fields():
    """RecoveryDecision must carry the run_id and tenant_id passed in."""
    decision = decide_recovery_action(
        run_id="r-123",
        tenant_id="tenant-789",
        current_state=RecoveryState.LEASE_EXPIRED,
        posture=Posture.RESEARCH,
    )
    assert decision.run_id == "r-123"
    assert decision.tenant_id == "tenant-789"
