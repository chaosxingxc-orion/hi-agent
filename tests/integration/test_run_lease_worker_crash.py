"""Integration test: stopping the heartbeat causes the lease to expire.

Verifies that when the heartbeat loop is disabled (simulating a worker crash),
the lease expires and another worker can claim the run via release_expired_leases.

Layer 2 — Integration: real RunQueue (SQLite :memory:).
No mocks on the subsystem under test.
"""

from __future__ import annotations

import time

import pytest

from hi_agent.server.run_queue import RunQueue


@pytest.mark.integration
def test_no_heartbeat_causes_lease_expiry_and_adoption() -> None:
    """Without heartbeat, the lease expires and a second worker can claim the run.

    This is the inverse of test_run_lease_heartbeat.py — it proves that
    heartbeat() is required; without it the run IS reclaimed.
    """
    lease_timeout = 0.5
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=lease_timeout)
    try:
        rq.enqueue("run-crash", priority=0, payload_json='{"goal": "survive crash"}')

        # Worker-A claims the run and then "crashes" (no heartbeat).
        item_a = rq.claim_next("worker-A")
        assert item_a is not None
        assert item_a["run_id"] == "run-crash"

        # Immediately Worker-B cannot claim it (still leased).
        assert rq.claim_next("worker-B") is None

        # Wait for the lease to expire (no heartbeat was sent).
        time.sleep(lease_timeout + 0.2)

        # Maintenance step: release expired leases.
        released = rq.release_expired_leases()
        assert released == 1, f"Expected 1 released lease, got {released}"

        # Worker-B can now claim the re-queued run.
        item_b = rq.claim_next("worker-B")
        assert item_b is not None, "Worker-B should claim the expired run"
        assert item_b["run_id"] == "run-crash"

        rq.complete("run-crash", "worker-B")
    finally:
        rq.close()


@pytest.mark.integration
def test_heartbeat_prevents_lease_expiry() -> None:
    """Periodic heartbeat() calls keep the lease alive past the original expiry.

    Proves that heartbeat() is effective: without expiry the run is NOT
    re-queued even after waiting past the initial lease_timeout.
    """
    lease_timeout = 0.5
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=lease_timeout)
    try:
        rq.enqueue("run-hb", priority=0, payload_json='{"goal": "keep alive"}')

        item = rq.claim_next("worker-A")
        assert item is not None
        assert item["run_id"] == "run-hb"

        # Send heartbeats for 3x the lease_timeout, each before expiry.
        deadline = time.monotonic() + lease_timeout * 3
        interval = lease_timeout / 3
        while time.monotonic() < deadline:
            renewed = rq.heartbeat("run-hb", "worker-A")
            assert renewed, "heartbeat() should return True while lease is valid"
            time.sleep(interval)

        # Even after the original expiry time, release_expired_leases
        # finds nothing because the lease was continuously extended.
        released = rq.release_expired_leases()
        assert released == 0, (
            f"No leases should have expired with active heartbeat; got {released}"
        )

        rq.complete("run-hb", "worker-A")
    finally:
        rq.close()
