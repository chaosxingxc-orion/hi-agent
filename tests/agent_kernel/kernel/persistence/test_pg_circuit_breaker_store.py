"""Unit tests for PostgresCircuitBreakerStore using a mock AsyncPGBridge.

Layer 1 — unit tests: mock only the AsyncPGBridge (external DB dependency).
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


def _make_mock_bridge(fetchrow_result=None, fetch_result=None, execute_result=None):
    """Build a mock AsyncPGBridge backed by a real background loop thread.

    Using a real background loop avoids the asyncio.run()-inside-running-loop
    RuntimeError that occurs when pytest-asyncio tests call run_sync during __init__.
    """
    loop, _thread = _make_loop_thread()

    bridge = MagicMock()

    def _run_sync(coro):
        return _run_on_loop(loop, coro)

    bridge.run_sync.side_effect = _run_sync

    # Build mock pool / connection
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.fetch = AsyncMock(return_value=fetch_result if fetch_result is not None else [])
    conn.execute = AsyncMock(return_value=execute_result)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx

    bridge.pool = pool
    return bridge, conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostgresCircuitBreakerStoreInstantiation:
    """Verify the store can be constructed with a pre-built bridge (no real DB)."""

    def test_instantiated_with_mock_bridge(self):
        """Store accepts a pre-built bridge without touching a real PostgreSQL server."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )

        bridge, _conn = _make_mock_bridge()
        store = PostgresCircuitBreakerStore(dsn="postgresql://mock", bridge=bridge)
        assert store is not None
        # Schema creation should have been called via run_sync
        assert bridge.run_sync.called

    def test_owns_bridge_flag_false_when_bridge_injected(self):
        """_own_bridge is False when a bridge is injected."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )

        bridge, _conn = _make_mock_bridge()
        store = PostgresCircuitBreakerStore(dsn="postgresql://mock", bridge=bridge)
        assert store._own_bridge is False


@pytest.mark.unit
class TestPostgresCircuitBreakerStoreGetState:
    """Verify get_state protocol contract."""

    def test_get_state_returns_zero_tuple_for_missing_key(self):
        """get_state returns (0, 0.0) when no row exists for the effect class."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )

        # fetchrow returns None -> no row exists
        bridge, _conn = _make_mock_bridge(fetchrow_result=None)
        store = PostgresCircuitBreakerStore(dsn="postgresql://mock", bridge=bridge)
        count, ts = store.get_state("payment.charge")
        assert count == 0
        assert ts == 0.0

    def test_get_state_returns_stored_values_when_row_present(self):
        """get_state returns the persisted (failure_count, last_failure_ts)."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )

        row = {"failure_count": 3, "last_failure_ts": 1_700_000_000.5}
        bridge, _conn = _make_mock_bridge(fetchrow_result=row)
        store = PostgresCircuitBreakerStore(dsn="postgresql://mock", bridge=bridge)
        count, ts = store.get_state("payment.charge")
        assert count == 3
        assert ts == pytest.approx(1_700_000_000.5)


@pytest.mark.unit
class TestPostgresCircuitBreakerStoreHelpers:
    """Verify alias methods and list_effect_classes."""

    def test_get_failure_count_delegates_to_get_state(self):
        """get_failure_count returns the count component of get_state."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )

        row = {"failure_count": 5, "last_failure_ts": 1_000.0}
        bridge, _conn = _make_mock_bridge(fetchrow_result=row)
        store = PostgresCircuitBreakerStore(dsn="postgresql://mock", bridge=bridge)
        assert store.get_failure_count("x") == 5

    def test_get_last_failure_ts_returns_none_for_zero_timestamp(self):
        """get_last_failure_ts returns None when ts is 0."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )

        bridge, _conn = _make_mock_bridge(fetchrow_result=None)
        store = PostgresCircuitBreakerStore(dsn="postgresql://mock", bridge=bridge)
        assert store.get_last_failure_ts("unknown") is None

    def test_list_effect_classes_returns_empty_list_for_empty_db(self):
        """list_effect_classes returns [] when the table is empty."""
        from agent_kernel.kernel.persistence.pg_circuit_breaker_store import (
            PostgresCircuitBreakerStore,
        )

        bridge, _conn = _make_mock_bridge(fetch_result=[])
        store = PostgresCircuitBreakerStore(dsn="postgresql://mock", bridge=bridge)
        result = store.list_effect_classes()
        assert result == []
