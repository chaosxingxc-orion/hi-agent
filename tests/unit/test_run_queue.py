"""Unit tests for RunQueue — SQLite-backed durable run queue."""

from __future__ import annotations

import time

import pytest
from hi_agent.server.run_queue import RunQueue


@pytest.fixture
def q() -> RunQueue:
    """In-memory RunQueue with a short lease timeout for test speed."""
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=1.0)
    yield rq
    rq.close()


class TestEnqueueAndClaimNext:
    def test_enqueue_then_claim_returns_run(self, q: RunQueue) -> None:
        q.enqueue("run-1", priority=0, payload_json='{"goal": "test"}')
        item = q.claim_next("worker-A")
        assert item is not None, f"Expected non-None result for item"
        assert item["run_id"] == "run-1"
        assert item["payload_json"] == '{"goal": "test"}'

    def test_enqueue_idempotent_by_run_id(self, q: RunQueue) -> None:
        q.enqueue("run-1", priority=0, payload_json="first")
        q.enqueue("run-1", priority=0, payload_json="second")  # ignored
        item = q.claim_next("worker-A")
        assert item is not None, f"Expected non-None result for item"
        assert item["payload_json"] == "first"  # second enqueue was a no-op
        # Queue should now be empty
        assert q.claim_next("worker-A") is None

    def test_claim_next_empty_queue_returns_none(self, q: RunQueue) -> None:
        assert q.claim_next("worker-A") is None

    def test_priority_ordering(self, q: RunQueue) -> None:
        q.enqueue("run-low", priority=10, payload_json="low")
        q.enqueue("run-high", priority=1, payload_json="high")
        item = q.claim_next("worker-A")
        assert item is not None, f"Expected non-None result for item"
        assert item["run_id"] == "run-high"


class TestTwoWorkersCantClaimSameRun:
    def test_two_workers_cannot_claim_same_run(self, q: RunQueue) -> None:
        """Two sequential claim_next calls on a single-item queue return
        the run to only one worker.
        """
        q.enqueue("run-1", priority=0)
        first = q.claim_next("worker-A")
        second = q.claim_next("worker-B")
        assert first is not None, f"Expected non-None result for first"
        assert second is None  # already leased; no more queued runs


class TestExpiredLeases:
    def test_release_expired_leases_makes_run_claimable_again(self, q: RunQueue) -> None:
        rq = RunQueue(db_path=":memory:", lease_timeout_seconds=0.05)
        try:
            rq.enqueue("run-1", priority=0)
            item = rq.claim_next("worker-A")
            assert item is not None, f"Expected non-None result for item"
            # Lease expires after 50 ms
            time.sleep(0.1)
            released = rq.release_expired_leases()
            assert released == 1
            reclaimed = rq.claim_next("worker-B")
            assert reclaimed is not None, f"Expected non-None result for reclaimed"
            assert reclaimed["run_id"] == "run-1"
        finally:
            rq.close()


class TestCancel:
    def test_cancel_sets_cancellation_flag(self, q: RunQueue) -> None:
        q.enqueue("run-1", priority=0)
        assert not q.is_cancelled("run-1")
        q.cancel("run-1")
        assert q.is_cancelled("run-1")

    def test_cancelled_run_not_claimable(self, q: RunQueue) -> None:
        q.enqueue("run-1", priority=0)
        q.cancel("run-1")
        assert q.claim_next("worker-A") is None

    def test_is_cancelled_unknown_run_returns_false(self, q: RunQueue) -> None:
        assert not q.is_cancelled("nonexistent")


class TestFailWithMaxAttempts:
    def test_fail_below_max_requeues(self, q: RunQueue) -> None:
        q.enqueue("run-1", priority=0)
        q.claim_next("worker-A")
        q.fail("run-1", "worker-A", "temporary error")
        # Should be back in queue
        item = q.claim_next("worker-B")
        assert item is not None, f"Expected non-None result for item"
        assert item["run_id"] == "run-1"

    def test_fail_at_max_attempts_marks_failed_not_requeued(self, q: RunQueue) -> None:
        q.enqueue("run-1", priority=0)
        # Exhaust all 3 attempts
        for attempt in range(3):
            worker = f"worker-{attempt}"
            q.claim_next(worker)
            q.fail("run-1", worker, "error")
        # After 3 failures the run should be in 'failed' state, not 'queued'
        assert q.claim_next("worker-final") is None

    def test_complete_removes_from_active_queue(self, q: RunQueue) -> None:
        q.enqueue("run-1", priority=0)
        q.claim_next("worker-A")
        q.complete("run-1", "worker-A")
        assert q.claim_next("worker-B") is None
