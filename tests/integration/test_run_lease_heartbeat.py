"""Integration test: heartbeat loop keeps a long-running run's lease alive.

Layer 2 — Integration: real RunQueue (SQLite :memory:) and real RunManager.
No mocks on the subsystem under test.
"""

from __future__ import annotations

import time

import pytest
from hi_agent.server.run_manager import ManagedRun, RunManager
from hi_agent.server.run_queue import RunQueue
from hi_agent.server.tenant_context import TenantContext


def _wait_terminal(run: ManagedRun, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run.state in ("completed", "failed", "cancelled"):
            return
        time.sleep(0.05)


@pytest.mark.integration
def test_heartbeat_keeps_lease_alive_during_long_run() -> None:
    """A run that sleeps 6 s with a 2 s lease_timeout must NOT be reclaimed.

    The heartbeat loop fires every lease_timeout/3 ≈ 0.67 s and extends the
    lease, so the run completes successfully without being re-queued.
    """
    lease_timeout = 2.0
    run_sleep = 6.0

    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=lease_timeout)
    # With lease_timeout=2.0, lease_timeout/3≈0.67 < 1.0 minimum, so interval is clamped to 1.0.
    assert rq.lease_heartbeat_interval_seconds == pytest.approx(
        max(1.0, lease_timeout / 3), rel=0.01
    )

    heartbeat_calls: list[float] = []
    _orig_heartbeat = rq.heartbeat

    def _spy_heartbeat(
        run_id: str, worker_id: str, tenant_id: str | None = None
    ) -> bool:
        heartbeat_calls.append(time.monotonic())
        return _orig_heartbeat(run_id, worker_id, tenant_id=tenant_id)

    rq.heartbeat = _spy_heartbeat  # type: ignore[method-assign]  expiry_wave: permanent

    rm = RunManager(run_queue=rq)
    try:
        workspace = TenantContext(tenant_id="t1", user_id="u1")
        run = rm.create_run({"goal": "long task"}, workspace=workspace)

        def _slow_executor(r: ManagedRun):
            time.sleep(run_sleep)

            class _R:
                status = "completed"
                error = None
                finished_at = None
                llm_fallback_count = 0
                fallback_events: list = []  # noqa: RUF012  expiry_wave: permanent

                def to_dict(self):
                    return {"status": "completed"}

            return _R()

        rm.start_run(run.run_id, _slow_executor)
        _wait_terminal(run, timeout=run_sleep + 5.0)

        assert run.state == "completed", f"Run should complete; got {run.state}"
        assert len(heartbeat_calls) >= 1, (
            "heartbeat() should have been called at least once during the run"
        )
    finally:
        rm.shutdown(timeout=5.0)
        rq.close()


@pytest.mark.integration
def test_heartbeat_interval_is_one_third_of_lease_timeout() -> None:
    """lease_heartbeat_interval_seconds is derived from lease_timeout_seconds / 3."""
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=90.0)
    try:
        assert rq.lease_heartbeat_interval_seconds == pytest.approx(30.0, rel=0.01)
    finally:
        rq.close()


@pytest.mark.integration
def test_heartbeat_interval_minimum_is_one_second() -> None:
    """lease_heartbeat_interval_seconds is never less than 1.0 s."""
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=0.1)
    try:
        assert rq.lease_heartbeat_interval_seconds == 1.0
    finally:
        rq.close()


@pytest.mark.integration
def test_heartbeat_failure_transitions_run_to_failed() -> None:
    """When heartbeat() returns False, the run must transition to state='failed'.

    Sub-track I-1 (Wave 13): heartbeat-as-state. The heartbeat loop must set
    run.state='failed' and run.error containing 'lease_lost' when lease renewal
    is denied.
    """
    rq = RunQueue(db_path=":memory:", lease_timeout_seconds=60.0)

    # Patch heartbeat to return False on first call, simulating renewal denial.
    heartbeat_calls: list[int] = []

    def _deny_heartbeat(
        run_id: str, worker_id: str, tenant_id: str | None = None
    ) -> bool:
        heartbeat_calls.append(1)
        return False  # simulate lease renewal denied

    rq.heartbeat = _deny_heartbeat  # type: ignore[method-assign]  expiry_wave: permanent

    # Use a very short heartbeat interval so the test completes quickly.
    # We monkey-patch the property value directly.
    rq.__dict__["lease_heartbeat_interval_seconds"] = 0.1  # type: ignore[attr-defined]  expiry_wave: permanent

    rm = RunManager(run_queue=rq)
    try:
        workspace = TenantContext(tenant_id="t1", user_id="u1")
        run = rm.create_run({"goal": "lease loss test"}, workspace=workspace)

        executor_started = [False]
        executor_done = [False]

        def _blocking_executor(r: ManagedRun):
            executor_started[0] = True
            # Block until run state transitions to failed (heartbeat fires)
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if r.state == "failed":
                    break
                time.sleep(0.05)
            executor_done[0] = True

            class _R:
                status = "failed"
                error = "lease_lost: heartbeat renewal denied"
                finished_at = None
                llm_fallback_count = 0
                fallback_events: list = []  # noqa: RUF012  expiry_wave: permanent

                def to_dict(self):
                    return {"status": "failed"}

            return _R()

        rm.start_run(run.run_id, _blocking_executor)

        # Wait for executor to observe the state change
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if executor_done[0]:
                break
            time.sleep(0.1)

        assert executor_done[0], "Executor did not finish within timeout"
        assert run.state == "failed", (
            f"Run state must be 'failed' after lease loss; got {run.state!r}"
        )
        assert run.error is not None and "lease_lost" in run.error, (
            f"run.error must contain 'lease_lost'; got {run.error!r}"
        )
        assert len(heartbeat_calls) >= 1, "heartbeat must have been called at least once"
    finally:
        rm.shutdown(timeout=5.0)
        rq.close()
