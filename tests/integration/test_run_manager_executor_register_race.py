"""Regression test for the create_run / start_run executor-registration race.

Layer 2 — Integration: real RunManager + real RunQueue (in-memory SQLite).

Background
----------
Before the fix, ``RunManager.create_run`` enqueued the new run into the
durable ``RunQueue`` *before* the route handler returned and called
``start_run`` — so the background ``_queue_worker`` could claim the run,
look up ``self._pending_executors[run_id]``, find ``None``, and call
``RunQueue.fail()`` with ``"executor_not_found"``.  Because
``RunQueue.fail()`` increments ``attempt_count`` each time, the run was
DLQed after ``max_attempts=3`` retries and never executed — the smoke
test then saw ``state="created"`` for the full 60s timeout.

This test simulates the race deterministically by:
  1. Calling ``create_run`` (which used to immediately enqueue).
  2. Sleeping briefly so the worker (already running from a prior
     ``start_run``) has a chance to iterate.
  3. Calling ``start_run``.
  4. Asserting the run reaches a terminal state (``completed``).

With the fix in place, ``create_run`` does NOT enqueue; ``start_run``
registers the executor in ``_pending_executors`` *and then* enqueues to
the durable queue, eliminating the race entirely.
"""
from __future__ import annotations

import threading
import time

import pytest
from hi_agent.server.run_manager import ManagedRun, RunManager
from hi_agent.server.run_queue import RunQueue
from hi_agent.server.tenant_context import TenantContext


@pytest.fixture()
def manager(tmp_path):
    """RunManager wired with a real durable RunQueue (file-backed)."""
    rq = RunQueue(db_path=str(tmp_path / "queue.db"))
    rm = RunManager(run_queue=rq)
    yield rm
    rm.shutdown()


def _ok_executor(run: ManagedRun):
    """Trivial executor that returns a completed-status result."""
    class _R:
        status = "completed"
        error = None
        finished_at = None
        llm_fallback_count = 0
        fallback_events: list = []  # noqa: RUF012  expiry_wave: permanent

        def to_dict(self):
            return {"status": "completed"}
    return _R()


def _wait_terminal(run: ManagedRun, timeout: float = 5.0) -> None:
    """Block until run.state reaches a terminal value or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run.state in ("completed", "failed", "cancelled"):
            return
        time.sleep(0.05)


class TestExecutorRegisterRace:
    """The smoke-test scenario: rapid create_run + start_run pairs must
    never DLQ a run via the executor-not-found path."""

    def test_rapid_sequence_completes(self, manager):
        """Eight rapid create_run/start_run pairs must all complete."""
        workspace = TenantContext(tenant_id="t1", user_id="u1")
        runs = []
        for i in range(8):
            run = manager.create_run({"goal": f"smoke {i}"}, workspace=workspace)
            manager.start_run(run.run_id, _ok_executor)
            runs.append(run)

        for run in runs:
            _wait_terminal(run, timeout=5.0)
            assert run.state == "completed", (
                f"run {run.run_id!r} stuck at state={run.state!r}; "
                "create_run/start_run race regressed"
            )

    def test_slow_executor_factory_does_not_lose_run(self, manager):
        """Simulate the production scenario where ``executor_factory`` is
        slow (kernel + LLM gateway construction).  Even with a 100ms gap
        between ``create_run`` and ``start_run``, the run must execute.
        """
        workspace = TenantContext(tenant_id="t1", user_id="u1")

        # Pre-warm the worker with a quick run so the background thread is
        # already iterating when the next create_run lands.
        warmup = manager.create_run({"goal": "warmup"}, workspace=workspace)
        manager.start_run(warmup.run_id, _ok_executor)
        _wait_terminal(warmup, timeout=5.0)
        assert warmup.state == "completed"

        # Now simulate a slow factory: create_run, sleep, start_run.
        # Pre-fix this would DLQ the run after 3 worker iterations.
        run = manager.create_run({"goal": "slow"}, workspace=workspace)
        time.sleep(0.3)  # plenty of time for the worker to race
        manager.start_run(run.run_id, _ok_executor)

        _wait_terminal(run, timeout=5.0)
        assert run.state == "completed", (
            f"run stuck at {run.state!r} — executor-not-found race regressed"
        )

    def test_concurrent_creators(self, manager):
        """Multiple threads creating runs simultaneously must not race."""
        workspace = TenantContext(tenant_id="t1", user_id="u1")
        results: list[ManagedRun] = []
        lock = threading.Lock()

        def _create_and_start(idx: int) -> None:
            run = manager.create_run({"goal": f"thr {idx}"}, workspace=workspace)
            manager.start_run(run.run_id, _ok_executor)
            with lock:
                results.append(run)

        threads = [threading.Thread(target=_create_and_start, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 6
        for run in results:
            _wait_terminal(run, timeout=5.0)
            assert run.state == "completed", (
                f"concurrent run stuck at {run.state!r}"
            )
