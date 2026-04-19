"""Integration test: lease expiry allows a second worker to claim a crashed run."""

from __future__ import annotations

import time

from hi_agent.server.run_queue import RunQueue


def test_crashed_worker_lease_expires_and_second_worker_claims() -> None:
    """Worker-A claims a run but never sends a heartbeat or calls complete/fail.

    After the lease expires, ``release_expired_leases`` must re-queue the run
    so Worker-B can claim it.
    """
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=0.1)
    try:
        rq.enqueue("run-crashed", priority=0, payload_json='{"goal": "recover"}')

        # Worker-A claims and then "crashes" (no heartbeat, no complete/fail).
        item_a = rq.claim_next("worker-A")
        assert item_a is not None, "Worker-A should have claimed the run"
        assert item_a["run_id"] == "run-crashed"

        # Simulate crash: Worker-B tries immediately — should get nothing.
        item_b_before = rq.claim_next("worker-B")
        assert item_b_before is None, "Run is still leased; Worker-B should not claim it"

        # Wait for lease to expire.
        time.sleep(0.2)

        # Release expired leases (maintenance step).
        released = rq.release_expired_leases()
        assert released == 1, f"Expected 1 released lease, got {released}"

        # Worker-B can now claim the run.
        item_b = rq.claim_next("worker-B")
        assert item_b is not None, "Worker-B should claim the re-queued run"
        assert item_b["run_id"] == "run-crashed"
        assert item_b["payload_json"] == '{"goal": "recover"}'

        # Worker-B completes successfully.
        rq.complete("run-crashed", "worker-B")

        # No more runs available.
        assert rq.claim_next("worker-C") is None
    finally:
        rq.close()
