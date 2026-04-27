"""Integration test: heartbeat loop keeps a long-running run's lease alive.

Layer 2 — Integration: real RunQueue (SQLite :memory:) and real RunManager.
No mocks on the subsystem under test.
"""

from __future__ import annotations

import threading
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

    def _spy_heartbeat(run_id: str, worker_id: str) -> bool:
        heartbeat_calls.append(time.monotonic())
        return _orig_heartbeat(run_id, worker_id)

    rq.heartbeat = _spy_heartbeat  # type: ignore[method-assign]

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
                fallback_events: list = []  # noqa: RUF012

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
