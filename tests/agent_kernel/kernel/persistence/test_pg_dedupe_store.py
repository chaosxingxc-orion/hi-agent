"""Unit tests for PostgresDedupeStore using a mock AsyncPGBridge.

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
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.fetch = AsyncMock(return_value=fetch_result if fetch_result is not None else [])
    conn.execute = AsyncMock(return_value=execute_result)
    # transaction() must return an async context manager (not a coroutine)
    tx_ctx = MagicMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx_ctx)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx

    bridge.pool = pool
    return bridge, conn


def _make_envelope(key: str = "key-1"):
    """Build a minimal IdempotencyEnvelope for testing."""
    from agent_kernel.kernel.dedupe_store import IdempotencyEnvelope

    return IdempotencyEnvelope(
        dispatch_idempotency_key=key,
        operation_fingerprint="fp-abc",
        attempt_seq=1,
        effect_scope="local_write",
        capability_snapshot_hash="hash-123",
        host_kind="in_process_python",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostgresDedupeStoreInstantiation:
    """Verify the store can be constructed with a pre-built bridge."""

    def test_instantiated_with_mock_bridge(self):
        """Store accepts a pre-built bridge without touching a real PostgreSQL server."""
        from agent_kernel.kernel.persistence.pg_dedupe_store import PostgresDedupeStore

        bridge, _conn = _make_mock_bridge()
        store = PostgresDedupeStore(dsn="postgresql://mock", bridge=bridge)
        assert store is not None

    def test_owns_bridge_flag_false_when_bridge_injected(self):
        """_own_bridge is False when a bridge is injected."""
        from agent_kernel.kernel.persistence.pg_dedupe_store import PostgresDedupeStore

        bridge, _conn = _make_mock_bridge()
        store = PostgresDedupeStore(dsn="postgresql://mock", bridge=bridge)
        assert store._own_bridge is False


@pytest.mark.unit
class TestPostgresDedupeStoreGet:
    """Verify get() protocol contract."""

    def test_get_returns_none_for_missing_key(self):
        """get() returns None when no row exists for the given key."""
        from agent_kernel.kernel.persistence.pg_dedupe_store import PostgresDedupeStore

        bridge, _conn = _make_mock_bridge(fetchrow_result=None)
        store = PostgresDedupeStore(dsn="postgresql://mock", bridge=bridge)
        result = store.get("nonexistent-key")
        assert result is None

    def test_get_returns_dedupe_record_when_row_exists(self):
        """get() returns a DedupeRecord when a row exists."""
        from agent_kernel.kernel.dedupe_store import DedupeRecord
        from agent_kernel.kernel.persistence.pg_dedupe_store import PostgresDedupeStore

        row = {
            "dispatch_idempotency_key": "key-1",
            "operation_fingerprint": "fp-abc",
            "attempt_seq": 1,
            "state": "reserved",
            "peer_operation_id": None,
            "external_ack_ref": None,
        }
        bridge, _conn = _make_mock_bridge(fetchrow_result=row)
        store = PostgresDedupeStore(dsn="postgresql://mock", bridge=bridge)
        record = store.get("key-1")
        assert record is not None
        assert isinstance(record, DedupeRecord)
        assert record.dispatch_idempotency_key == "key-1"
        assert record.state == "reserved"


@pytest.mark.unit
class TestPostgresDedupeStoreReserve:
    """Verify reserve() protocol contract."""

    def test_reserve_accepted_when_insert_returns_row(self):
        """reserve() returns DedupeReservation(accepted=True) on fresh insert."""
        from agent_kernel.kernel.persistence.pg_dedupe_store import PostgresDedupeStore

        # fetchrow returns a row -> INSERT succeeded (no conflict)
        inserted_row = {"dispatch_idempotency_key": "key-1"}
        bridge, _conn = _make_mock_bridge(fetchrow_result=inserted_row)
        store = PostgresDedupeStore(dsn="postgresql://mock", bridge=bridge)
        envelope = _make_envelope("key-1")
        reservation = store.reserve(envelope)
        assert reservation.accepted is True
        assert reservation.reason == "accepted"
