"""Unit tests for SyncBridge shutdown — W12-I.3.

Verifies that calling shutdown() stops the background thread cleanly,
preventing loop.run_forever() from hanging indefinitely in tests.

Layer 1 (Unit): exercises SyncBridge lifecycle directly; no external I/O.
"""

from __future__ import annotations

import asyncio

from hi_agent.runtime.sync_bridge import SyncBridge, SyncBridgeShutdownError


def test_sync_bridge_thread_exits_after_shutdown():
    """After shutdown(), the bridge thread must exit within 2 seconds."""
    bridge = SyncBridge()

    # Force the background thread to start by making one call.
    result = bridge.call_sync(asyncio.sleep(0))
    assert result is None

    assert bridge._thread is not None
    assert bridge._thread.is_alive()

    bridge.shutdown(timeout=2.0)

    bridge._thread.join(timeout=2.0)
    assert not bridge._thread.is_alive(), (
        "SyncBridge background thread must exit within 2 s after shutdown()"
    )


def test_call_sync_after_shutdown_raises():
    """call_sync() after shutdown must raise SyncBridgeShutdownError."""
    bridge = SyncBridge()
    bridge.call_sync(asyncio.sleep(0))
    bridge.shutdown(timeout=2.0)

    coro = asyncio.sleep(0)
    try:
        bridge.call_sync(coro)
        raise AssertionError("Expected SyncBridgeShutdownError was not raised")
    except SyncBridgeShutdownError:
        coro.close()  # prevent RuntimeWarning: coroutine was never awaited


def test_shutdown_before_start_is_safe():
    """shutdown() on a never-started bridge must not raise."""
    bridge = SyncBridge()
    bridge.shutdown()  # must not raise


def test_shutdown_idempotent():
    """Repeated shutdown() calls must be no-ops after the first."""
    bridge = SyncBridge()
    bridge.call_sync(asyncio.sleep(0))
    bridge.shutdown(timeout=2.0)
    bridge.shutdown(timeout=2.0)  # second call must not raise or hang
