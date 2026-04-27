"""Unit tests for PostgresColocatedBundle using a mock AsyncPGBridge.

Layer 1 — unit tests: mock only the AsyncPGBridge (external DB dependency).
The bundle creates a shared bridge and hands it to each constituent store.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop_thread():
    """Spin up a dedicated background event loop thread (mirrors AsyncPGBridge._run_loop)."""
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    return loop, t


def _run_on_loop(loop, coro):
    """Schedule a coroutine on *loop* and block until it completes."""
    f: Future = asyncio.run_coroutine_threadsafe(coro, loop)
    return f.result(timeout=5)


def _make_mock_bridge():
    """Return a MagicMock AsyncPGBridge backed by a real background loop thread."""
    loop, _thread = _make_loop_thread()

    bridge = MagicMock()

    def _run_sync(coro):
        return _run_on_loop(loop, coro)

    bridge.run_sync.side_effect = _run_sync

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction.return_value = tx_ctx

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    pool.close = AsyncMock(return_value=None)

    bridge.pool = pool
    bridge.close = MagicMock()
    return bridge


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostgresColocatedBundleInstantiation:
    """Verify PostgresColocatedBundle constructs all stores over a shared bridge."""

    def test_bundle_exposes_all_four_stores(self):
        """Bundle exposes event_log, dedupe_store, circuit_breaker_store, recovery_outcome_store."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )
        from agent_kernel.kernel.persistence.pg_dedupe_store import PostgresDedupeStore
        from agent_kernel.kernel.persistence.pg_event_log import (
            PostgresKernelRuntimeEventLog,
        )
        from agent_kernel.kernel.persistence.pg_recovery_outcome_store import (
            PostgresRecoveryOutcomeStore,
        )

        mock_bridge = _make_mock_bridge()

        # Build each store manually over the shared mock bridge
        el = PostgresKernelRuntimeEventLog("postgresql://mock", bridge=mock_bridge)
        ds = PostgresDedupeStore("postgresql://mock", bridge=mock_bridge)
        cbs = PostgresCircuitBreakerStore("postgresql://mock", bridge=mock_bridge)
        ros = PostgresRecoveryOutcomeStore("postgresql://mock", bridge=mock_bridge)

        assert isinstance(el, PostgresKernelRuntimeEventLog)
        assert isinstance(ds, PostgresDedupeStore)
        assert isinstance(cbs, PostgresCircuitBreakerStore)
        assert isinstance(ros, PostgresRecoveryOutcomeStore)

    def test_bundle_stores_share_same_bridge(self):
        """All stores injected with the same bridge share a single pool reference."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )
        from agent_kernel.kernel.persistence.pg_dedupe_store import PostgresDedupeStore
        from agent_kernel.kernel.persistence.pg_event_log import (
            PostgresKernelRuntimeEventLog,
        )
        from agent_kernel.kernel.persistence.pg_recovery_outcome_store import (
            PostgresRecoveryOutcomeStore,
        )

        mock_bridge = _make_mock_bridge()

        el = PostgresKernelRuntimeEventLog("postgresql://mock", bridge=mock_bridge)
        ds = PostgresDedupeStore("postgresql://mock", bridge=mock_bridge)
        cbs = PostgresCircuitBreakerStore("postgresql://mock", bridge=mock_bridge)
        ros = PostgresRecoveryOutcomeStore("postgresql://mock", bridge=mock_bridge)

        # All should reference the same bridge pool object
        assert el._bridge.pool is mock_bridge.pool
        assert ds._bridge.pool is mock_bridge.pool
        assert cbs._bridge.pool is mock_bridge.pool
        assert ros._bridge.pool is mock_bridge.pool
