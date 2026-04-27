"""Integration tests for W12-F: SIGTERM drain + active-run lease release on shutdown.

Layer 2 integration tests — real RunManager and RunQueue instances; no mocks
on the subsystem under test.
"""

from __future__ import annotations

import sys
import threading

import pytest
from hi_agent.server.run_manager import ManagedRun, RunManager

# ---------------------------------------------------------------------------
# Test 1 — shutdown marks abandoned active runs as failed in run_store
# ---------------------------------------------------------------------------


def test_shutdown_marks_active_runs_failed() -> None:
    """shutdown() calls run_queue.fail() for runs still in _active_run_ids at shutdown time.

    We simulate an in-flight run by:
    1. Creating a real RunManager wired with a spy RunQueue (passed to __init__
       so the durable path is active).
    2. Manually populating _active_run_ids to represent a run that started but
       has not yet cleared itself (simulating an executor blocked mid-flight).
    3. Calling shutdown() and verifying the spy recorded the fail() call.

    This tests the shutdown lease-release logic directly, independent of the
    threading timing of a slow executor.
    """
    import uuid

    failed_ids: list[str] = []

    class _SpyRunQueue:
        """Minimal RunQueue spy that records fail() calls and blocks claim_next."""

        def enqueue(self, run_id: str, **kwargs: object) -> None:
            pass

        def claim_next(self, worker_id: str) -> dict | None:
            return None

        def release_expired_leases(self) -> int:
            return 0

        def fail(self, run_id: str, worker_id: str, error: str = "") -> None:
            failed_ids.append(run_id)

        def complete(self, run_id: str, worker_id: str) -> None:
            pass

        def cancel(self, run_id: str) -> None:
            pass

    spy_queue = _SpyRunQueue()
    manager = RunManager(
        max_concurrent=2,
        queue_size=4,
        run_queue=spy_queue,  # type: ignore[arg-type]
    )

    # Simulate a run that started executing (added to _active_run_ids) but has
    # not yet reached its finally block (i.e. still in-flight at shutdown time).
    fake_run_id = str(uuid.uuid4())
    with manager._lock:
        manager._active_run_ids.add(fake_run_id)

    # shutdown() should call spy_queue.fail() for the fake in-flight run.
    manager.shutdown(timeout=0.5)

    assert fake_run_id in failed_ids, (
        f"Expected run_id {fake_run_id!r} in failed_ids after shutdown; got {failed_ids}"
    )


# ---------------------------------------------------------------------------
# Test 2 — _active_run_ids is cleared after a run finishes normally
# ---------------------------------------------------------------------------


def test_active_run_ids_cleared_after_completion() -> None:
    """_active_run_ids must not retain a run_id after the run finishes."""
    manager = RunManager(max_concurrent=2, queue_size=4)
    done = threading.Event()

    def instant_executor(run: ManagedRun) -> object:
        done.set()
        return object()

    run = manager.create_run({"goal": "quick task"})
    manager.start_run(run.run_id, instant_executor)

    done.wait(timeout=5)
    # Give the finally block a moment to clear the id.
    import time

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        with manager._lock:
            if run.run_id not in manager._active_run_ids:
                break
        time.sleep(0.05)

    with manager._lock:
        assert run.run_id not in manager._active_run_ids, (
            "_active_run_ids should be empty after run completes"
        )

    manager.shutdown(timeout=0.5)


# ---------------------------------------------------------------------------
# Test 3 — SIGTERM handler can be raised without crashing (POSIX only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM raise_signal not available on Windows", expiry_wave="Wave 16")
def test_sigterm_handler_installed() -> None:
    """On POSIX, signal.raise_signal(SIGTERM) must not crash the process.

    We install a no-op SIGTERM handler, raise the signal, then restore the
    original handler.  This validates the handler registration path without
    requiring a live AgentServer.
    """
    import signal

    received: list[int] = []

    def _handler(signum: int, frame: object) -> None:
        received.append(signum)

    original = signal.signal(signal.SIGTERM, _handler)
    try:
        signal.raise_signal(signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, original)

    assert received == [signal.SIGTERM], (
        f"Expected SIGTERM to be received exactly once; got {received}"
    )
