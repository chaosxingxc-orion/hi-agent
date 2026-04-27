"""Unit tests for AsyncPGBridge (pg_shared.py).

Layer 1 — unit: patch asyncpg via sys.modules to avoid a real DB connection.
asyncpg is an optional dependency imported lazily inside _create_pool().
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge_with_mock_pool():
    """Return an AsyncPGBridge with asyncpg injected via sys.modules."""
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock(return_value=None)

    mock_asyncpg = MagicMock()
    mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

    # Inject the mock module BEFORE importing AsyncPGBridge so that
    # the lazy `import asyncpg` inside _create_pool() finds the mock.
    sys.modules["asyncpg"] = mock_asyncpg

    try:
        # Re-import to pick up the mock (module may already be cached — force fresh)
        if "agent_kernel.kernel.persistence.pg_shared" in sys.modules:
            del sys.modules["agent_kernel.kernel.persistence.pg_shared"]
        from agent_kernel.kernel.persistence.pg_shared import AsyncPGBridge

        bridge = AsyncPGBridge(dsn="postgresql://mock", pool_min=1, pool_max=2)
    finally:
        # Restore: remove the injected mock so other tests are unaffected
        sys.modules.pop("asyncpg", None)

    return bridge, mock_pool


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAsyncPGBridgeInstantiation:
    """Verify AsyncPGBridge starts its background loop and exposes .pool."""

    def test_instantiated_with_mock_asyncpg(self):
        """Bridge initializes without a real PostgreSQL server when asyncpg is mocked."""
        bridge, mock_pool = _make_bridge_with_mock_pool()
        try:
            assert bridge is not None
            assert bridge.pool is mock_pool
        finally:
            bridge.close()

    def test_background_thread_is_alive_after_init(self):
        """Background event-loop thread starts and is alive after construction."""
        bridge, _ = _make_bridge_with_mock_pool()
        try:
            assert bridge._thread.is_alive()
        finally:
            bridge.close()

    def test_close_marks_bridge_as_closed(self):
        """close() sets _closed=True; second close() is idempotent."""
        bridge, _ = _make_bridge_with_mock_pool()
        bridge.close()
        assert bridge._closed is True
        # Second close should be a no-op (not raise)
        bridge.close()


@pytest.mark.unit
class TestAsyncPGBridgeRunSync:
    """Verify run_sync dispatches to the background loop and returns a result."""

    def test_run_sync_executes_simple_coroutine(self):
        """run_sync can execute a simple coroutine and return its result."""
        bridge, _ = _make_bridge_with_mock_pool()
        try:
            async def _add(a, b):
                return a + b

            result = bridge.run_sync(_add(2, 3))
            assert result == 5
        finally:
            bridge.close()


@pytest.mark.unit
class TestAsyncPGBridgeRunAsync:
    """Verify run_async wraps a coroutine and can be awaited."""

    @pytest.mark.asyncio
    async def test_run_async_executes_coroutine(self):
        """run_async schedules a coroutine on the bridge loop and returns its result."""
        bridge, _ = _make_bridge_with_mock_pool()
        try:
            async def _multiply(a, b):
                return a * b

            result = await bridge.run_async(_multiply(4, 5))
            assert result == 20
        finally:
            bridge.close()
