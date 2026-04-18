"""Verify that AsyncBridgeService creates exactly one executor per process lifetime."""

from __future__ import annotations

import asyncio
import time

import pytest

from hi_agent.runtime.async_bridge import AsyncBridgeService


def _reset_executor() -> None:
    """Reset the class-level executor so each test gets a clean state."""
    AsyncBridgeService._executor = None


def test_executor_singleton() -> None:
    """get_executor() returns the same object on repeated calls."""
    _reset_executor()
    e1 = AsyncBridgeService.get_executor()
    e2 = AsyncBridgeService.get_executor()
    assert e1 is e2


def test_executor_thread_name_prefix() -> None:
    """Created executor uses the expected thread name prefix."""
    _reset_executor()
    executor = AsyncBridgeService.get_executor()
    # ThreadPoolExecutor stores the prefix as _thread_name_prefix (CPython impl detail)
    assert "async_bridge" in (executor._thread_name_prefix or "")


def test_run_sync_returns_value() -> None:
    """run_sync executes a callable and returns its result."""
    _reset_executor()

    async def _run() -> int:
        return await AsyncBridgeService.run_sync(lambda: 42)

    result = asyncio.run(_run())
    assert result == 42


def test_run_sync_timeout() -> None:
    """run_sync raises asyncio.TimeoutError when the callable exceeds the budget."""
    _reset_executor()

    def _slow() -> None:
        time.sleep(10)

    async def _run() -> None:
        await AsyncBridgeService.run_sync(_slow, timeout=0.05)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(_run())


def test_executor_creation_count_is_one() -> None:
    """Executor is created exactly once across multiple repeated get_executor calls."""
    _reset_executor()
    executors = [AsyncBridgeService.get_executor() for _ in range(10)]
    # All references must point to the same object.
    assert all(e is executors[0] for e in executors), "Multiple executor instances created"


def test_run_sync_in_thread_no_event_loop() -> None:
    """run_sync_in_thread works from synchronous context without an event loop."""
    _reset_executor()
    result = AsyncBridgeService.run_sync_in_thread(lambda: "sync_ok")
    assert result == "sync_ok"
