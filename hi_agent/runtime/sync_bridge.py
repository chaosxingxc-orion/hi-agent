"""Durable sync→async bridge backed by a single process-lifetime event loop.

Rule 12 (Async/Sync Resource Lifetime) requires that async resources such as
``httpx.AsyncClient`` connection pools, async iterators, and asyncio
``TaskGroup`` objects live on a **single** event loop for their entire
lifetime.  The historical pattern of calling ``asyncio.run(coro)`` from sync
code creates a *new* loop per call, which closes immediately when the call
returns — any resource constructed inside that coroutine (and any resource
whose first touch happened on that loop) is bound to a loop that no longer
exists.  Subsequent calls from the same sync caller then fail with
``RuntimeError: Event loop is closed`` (the 04-22 prod incident).

``SyncBridge`` solves this by running exactly one ``asyncio`` event loop on a
daemon thread for the life of the process.  Every ``call_sync(coro)``
invocation is scheduled onto that shared loop via
``asyncio.run_coroutine_threadsafe``, so a resource constructed by one
``call_sync`` call remains valid for every subsequent call.

Usage::

    from hi_agent.runtime.sync_bridge import get_bridge

    bridge = get_bridge()

    async def _build():
        return httpx.AsyncClient(timeout=5.0)

    client = bridge.call_sync(_build())        # built on the bridge loop

    async def _get(c, url):
        return await c.get(url)

    for url in urls:
        resp = bridge.call_sync(_get(client, url))  # same loop, same pool

    bridge.call_sync(client.aclose())

The module-level :func:`get_bridge` returns the process-wide singleton and
registers :meth:`SyncBridge.shutdown` with :mod:`atexit` on first use.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class SyncBridgeError(Exception):
    """Base exception for sync-bridge failures."""


class SyncBridgeShutdownError(SyncBridgeError):
    """Raised when :meth:`SyncBridge.call_sync` is invoked after shutdown."""


class SyncBridge:
    """Runs a persistent asyncio event loop on a daemon thread.

    The bridge guarantees: every :meth:`call_sync` invocation executes on the
    *same* event loop, so async resources (``httpx.AsyncClient`` pools, async
    iterators, task groups) can be constructed once and reused across many
    sync-facing calls.

    Instances are cheap to construct but only spawn their backing thread on
    the first :meth:`call_sync` call (lazy start).  Use :func:`get_bridge`
    for the process-wide singleton.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._started = False
        self._shutdown = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def _ensure_started(self) -> None:
        """Start the background loop thread on first use."""
        with self._lock:
            if self._shutdown:
                raise SyncBridgeShutdownError("bridge has been shut down")
            if self._started:
                return
            self._thread = threading.Thread(
                target=self._run,
                name="hi-agent-sync-bridge",
                daemon=True,
            )
            self._thread.start()
            if not self._ready.wait(timeout=5.0):
                raise SyncBridgeError(
                    "sync bridge thread failed to start within 5s"
                )
            self._started = True

    def _run(self) -> None:
        """Thread entrypoint — owns the event loop for the bridge's lifetime."""
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                # Best-effort asyncgen teardown — the loop is terminating
                # anyway, so we don't care which exception type escapes.
                with contextlib.suppress(Exception):  # rule7-exempt: expiry_wave="Wave 26" asyncgen teardown on loop close  # noqa: E501
                    loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def call_sync(
        self,
        coro: Coroutine[Any, Any, T],
        *,
        timeout: float | None = None,
    ) -> T:
        """Schedule *coro* on the bridge loop and block until it completes.

        Args:
            coro: The coroutine object to run.  Must not already be scheduled.
            timeout: Wall-clock seconds to wait before raising
                ``concurrent.futures.TimeoutError``.  ``None`` waits forever.

        Returns:
            The value returned by the coroutine.

        Raises:
            SyncBridgeShutdownError: if :meth:`shutdown` has been called.
            SyncBridgeError: if the background thread could not be started.
            concurrent.futures.TimeoutError: if *timeout* elapses.
            BaseException: any exception raised inside *coro* is re-raised
                verbatim to the sync caller.
        """
        self._ensure_started()
        assert self._loop is not None  # set before _ready.set()
        # w25-F: spine tap for sync_bridge layer
        with contextlib.suppress(Exception):  # rule7-exempt: spine emitters must never block execution path  # noqa: E501  # expiry_wave: Wave 26
            from hi_agent.observability.spine_events import emit_sync_bridge
            emit_sync_bridge()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def shutdown(self, *, timeout: float = 5.0) -> None:
        """Stop the bridge loop and join its thread.

        Idempotent: repeated calls after the first are no-ops.  Safe to call
        from any thread; ``atexit`` invokes this automatically via
        :func:`get_bridge`.
        """
        with self._lock:
            if self._shutdown:
                return
            if not self._started:
                # never started — just mark shut down so future calls fail
                self._shutdown = True
                return
            self._shutdown = True
            loop = self._loop
            thread = self._thread

        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=timeout)


# ---------------------------------------------------------------------------
# process-wide singleton
# ---------------------------------------------------------------------------
_bridge: SyncBridge | None = None
_bridge_lock = threading.Lock()


def get_bridge() -> SyncBridge:
    """Return the process-wide :class:`SyncBridge` singleton.

    Thread-safe.  On first call, registers :meth:`SyncBridge.shutdown` with
    :mod:`atexit` so the background thread is drained at interpreter exit.
    """
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            bridge = SyncBridge()
            atexit.register(bridge.shutdown)
            _bridge = bridge
        return _bridge


__all__ = [
    "SyncBridge",
    "SyncBridgeError",
    "SyncBridgeShutdownError",
    "get_bridge",
]
