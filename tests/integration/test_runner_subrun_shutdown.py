"""Integration test: runner._reap_pending_subruns() clears futures on shutdown.

Verifies that the new async reap path added to Runner cancels and awaits
pending subrun futures within the given timeout, and that
_pending_subrun_futures is empty after the call.

This tests the second fix in the DF-18 class Track V commit:
runner.py:_reap_pending_subruns() — tasks must not leak until GC.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_reap_pending_subruns_cancels_and_clears():
    """_reap_pending_subruns() must cancel pending futures and clear the map.

    We inject two synthetic futures directly into runner._pending_subrun_futures:
    - one that is already done
    - one that is still running (will be cancelled)

    After _reap_pending_subruns(), both must be cleared.
    """
    # Build a minimal Runner without triggering full DI setup.
    # We access only _pending_subrun_futures and _reap_pending_subruns().
    from hi_agent.runner import RunExecutor as Runner

    # Create a never-resolving coroutine to simulate an in-flight subrun task.
    async def _never_resolve():
        await asyncio.sleep(3600)

    loop = asyncio.get_running_loop()
    running_task = loop.create_task(_never_resolve())
    done_task = loop.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)  # let done_task finish

    # We need a Runner instance.  Build the lightest possible one by patching
    # the __init__ to skip all DI validation, then manually set the field.
    class _BarebonesRunner:
        """Minimal shim that exposes only _reap_pending_subruns and its field."""

        # Bind the real method so we don't have to construct a full Runner.
        _reap_pending_subruns = Runner._reap_pending_subruns

        def __init__(self):
            self._pending_subrun_futures: dict = {}

    runner = _BarebonesRunner()
    runner._pending_subrun_futures = {
        "task-done": done_task,
        "task-running": running_task,
    }

    await runner._reap_pending_subruns(timeout=1.0)

    assert runner._pending_subrun_futures == {}, (
        "_pending_subrun_futures must be empty after _reap_pending_subruns()"
    )
    # The running task must have been cancelled (done, with CancelledError).
    assert running_task.done(), "Running task must be done after reap"
    assert running_task.cancelled(), "Running task must be cancelled after reap"


@pytest.mark.asyncio
async def test_reap_pending_subruns_tolerates_empty_map():
    """_reap_pending_subruns() must not raise when there are no pending futures."""
    from hi_agent.runner import RunExecutor as Runner

    class _BarebonesRunner:
        _reap_pending_subruns = Runner._reap_pending_subruns

        def __init__(self):
            self._pending_subrun_futures: dict = {}

    runner = _BarebonesRunner()
    await runner._reap_pending_subruns(timeout=1.0)  # must not raise
    assert runner._pending_subrun_futures == {}


@pytest.mark.asyncio
async def test_reap_pending_subruns_tolerates_already_done_futures():
    """_reap_pending_subruns() must not raise when all futures are already done."""
    from hi_agent.runner import RunExecutor as Runner

    class _BarebonesRunner:
        _reap_pending_subruns = Runner._reap_pending_subruns

        def __init__(self):
            self._pending_subrun_futures: dict = {}

    loop = asyncio.get_running_loop()
    done1 = loop.create_task(asyncio.sleep(0))
    done2 = loop.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)  # let both finish

    runner = _BarebonesRunner()
    runner._pending_subrun_futures = {"a": done1, "b": done2}

    await runner._reap_pending_subruns(timeout=1.0)
    assert runner._pending_subrun_futures == {}
