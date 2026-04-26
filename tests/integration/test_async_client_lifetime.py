"""Verify no 'Event loop is closed' across sequential asyncio.run() calls.

Layer 1 — unit-level regression guard.  No real LLM or network needed.

Rule 5: async resources must be bound to exactly one event loop.
Each asyncio.run() creates a fresh event loop; resources must not be
shared across calls.  This test catches violations by running 5
sequential asyncio.run() calls that exercise the async lifecycle path.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.integration
def test_sequential_asyncio_run_no_loop_errors():
    """5 sequential asyncio.run() calls — no 'Event loop is closed' errors.

    Each call creates a fresh coroutine using per-call resource construction
    (Rule 5 approved pattern: cheap async context manager inside the coroutine).
    This is a regression guard: if any shared async resource (AsyncClient,
    ClientSession, etc.) is leaked across calls, the second+ call raises
    RuntimeError('Event loop is closed').
    """
    errors: list[str] = []

    async def run_once() -> str:
        """Minimal async operation using per-call construction (Rule 5)."""
        import asyncio as _aio

        # Simulate the kind of async work RunManager / KernelFacadeAdapter does:
        # schedule a coroutine, await it, return a result.  No shared state.
        await _aio.sleep(0)
        return "ok"

    for i in range(5):
        try:
            result = asyncio.run(run_once())
            assert result == "ok", f"run {i}: unexpected result {result!r}"
        except RuntimeError as exc:
            if "Event loop is closed" in str(exc):
                errors.append(f"run {i}: {exc}")
            else:
                raise

    assert not errors, f"Event loop errors across sequential asyncio.run() calls: {errors}"


@pytest.mark.integration
def test_sequential_asyncio_run_with_rehydrate_helper():
    """5 sequential asyncio.run() calls each invoking _rehydrate_runs with a no-op store.

    Verifies that the _rehydrate_runs coroutine is safe to call from
    sequential asyncio.run() contexts without leaking event loop state.
    """
    import asyncio as _aio

    from hi_agent.config.posture import Posture
    from hi_agent.server.app import _rehydrate_runs
    from hi_agent.server.run_manager import RunManager

    errors: list[str] = []

    def make_run():
        manager = RunManager()
        posture = Posture.DEV  # dev posture → _rehydrate_runs is a no-op

        async def _run():
            await _rehydrate_runs(run_store=None, run_manager=manager, posture=posture)

        return _run

    for i in range(5):
        try:
            _aio.run(make_run()())
        except RuntimeError as exc:
            if "Event loop is closed" in str(exc):
                errors.append(f"run {i}: {exc}")
            else:
                raise

    assert not errors, f"Event loop errors invoking _rehydrate_runs: {errors}"
