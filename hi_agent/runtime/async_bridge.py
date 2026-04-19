"""Shared async↔sync bridge backed by a process-lifetime ThreadPoolExecutor.

Replaces per-call ``ThreadPoolExecutor(max_workers=1)`` allocations.  A single
executor is created the first time it is requested and reused for the process
lifetime, eliminating repeated thread-pool creation overhead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar


class AsyncBridgeService:
    """Process-lifetime executor for sync→async bridging."""

    _executor: ClassVar[ThreadPoolExecutor | None] = None
    _MAX_WORKERS: ClassVar[int] = 8

    @classmethod
    def get_executor(cls) -> ThreadPoolExecutor:
        """Return the shared executor, creating it on first call."""
        if cls._executor is None:
            cls._executor = ThreadPoolExecutor(
                max_workers=cls._MAX_WORKERS,
                thread_name_prefix="async_bridge",
            )
        return cls._executor

    @classmethod
    async def run_sync(
        cls,
        fn: Callable[..., Any],
        *args: Any,
        timeout: float | None = None,
    ) -> Any:
        """Run a synchronous callable in the shared executor.

        Args:
            fn: Synchronous callable to run.
            *args: Positional arguments forwarded to *fn*.
            timeout: Optional wall-clock timeout in seconds.

        Raises:
            asyncio.TimeoutError: When *timeout* elapses before completion.
        """
        loop = asyncio.get_running_loop()
        coro = loop.run_in_executor(cls.get_executor(), fn, *args)
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    @classmethod
    def run_sync_in_thread(
        cls,
        fn: Callable[..., Any],
        *args: Any,
        timeout: float | None = None,
    ) -> Any:
        """Run a synchronous callable from a synchronous context via the shared executor.

        Used when there is no running event loop (e.g. in sync code that needs
        to offload a blocking call without creating a new thread pool).
        """
        future = cls.get_executor().submit(fn, *args)
        return future.result(timeout=timeout)
