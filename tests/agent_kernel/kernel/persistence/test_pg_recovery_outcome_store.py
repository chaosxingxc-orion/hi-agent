"""Unit tests for PostgresRecoveryOutcomeStore using a mock AsyncPGBridge.

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

    async def _run_async(coro):
        return await coro

    bridge.run_sync.side_effect = _run_sync
    bridge.run_async = AsyncMock(side_effect=_run_async)

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


def _make_recovery_outcome(run_id: str = "run-1"):
    """Build a minimal RecoveryOutcome for testing."""
    from agent_kernel.kernel.contracts import RecoveryOutcome

    return RecoveryOutcome(
        run_id=run_id,
        action_id="action-1",
        recovery_mode="abort",
        outcome_state="aborted",
        written_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostgresRecoveryOutcomeStoreInstantiation:
    """Verify the store can be constructed with a pre-built bridge."""

    def test_instantiated_with_mock_bridge(self):
        """Store accepts a pre-built bridge without touching a real PostgreSQL server."""
        from agent_kernel.kernel.persistence.pg_recovery_outcome_store import (
            PostgresRecoveryOutcomeStore,
        )

        bridge, _conn = _make_mock_bridge()
        store = PostgresRecoveryOutcomeStore(dsn="postgresql://mock", bridge=bridge)
        assert store is not None

    def test_owns_bridge_flag_false_when_bridge_injected(self):
        """_own_bridge is False when a bridge is injected."""
        from agent_kernel.kernel.persistence.pg_recovery_outcome_store import (
            PostgresRecoveryOutcomeStore,
        )

        bridge, _conn = _make_mock_bridge()
        store = PostgresRecoveryOutcomeStore(dsn="postgresql://mock", bridge=bridge)
        assert store._own_bridge is False


@pytest.mark.unit
class TestPostgresRecoveryOutcomeStoreLatestForRun:
    """Verify latest_for_run() protocol contract."""

    @pytest.mark.asyncio
    async def test_latest_for_run_returns_none_for_unknown_run(self):
        """latest_for_run() returns None when no row exists for the run_id."""
        from agent_kernel.kernel.persistence.pg_recovery_outcome_store import (
            PostgresRecoveryOutcomeStore,
        )

        bridge, _conn = _make_mock_bridge(fetchrow_result=None)
        store = PostgresRecoveryOutcomeStore(dsn="postgresql://mock", bridge=bridge)
        result = await store.latest_for_run("nonexistent-run")
        assert result is None

    @pytest.mark.asyncio
    async def test_latest_for_run_returns_outcome_when_row_exists(self):
        """latest_for_run() returns a RecoveryOutcome when a row exists."""
        from agent_kernel.kernel.contracts import RecoveryOutcome
        from agent_kernel.kernel.persistence.pg_recovery_outcome_store import (
            PostgresRecoveryOutcomeStore,
        )

        row = {
            "run_id": "run-1",
            "action_id": "action-1",
            "recovery_mode": "abort",
            "outcome_state": "aborted",
            "written_at": "2026-01-01T00:00:00Z",
            "operator_escalation_ref": None,
            "emitted_event_ids_json": '["evt-1", "evt-2"]',
        }
        bridge, _conn = _make_mock_bridge(fetchrow_result=row)
        store = PostgresRecoveryOutcomeStore(dsn="postgresql://mock", bridge=bridge)
        outcome = await store.latest_for_run("run-1")
        assert outcome is not None
        assert isinstance(outcome, RecoveryOutcome)
        assert outcome.run_id == "run-1"
        assert outcome.outcome_state == "aborted"
        assert outcome.emitted_event_ids == ["evt-1", "evt-2"]

    @pytest.mark.asyncio
    async def test_latest_for_run_handles_empty_emitted_event_ids(self):
        """latest_for_run() returns empty emitted_event_ids list on empty JSON array."""
        from agent_kernel.kernel.persistence.pg_recovery_outcome_store import (
            PostgresRecoveryOutcomeStore,
        )

        row = {
            "run_id": "run-2",
            "action_id": None,
            "recovery_mode": "reflect_and_retry",
            "outcome_state": "reflected",
            "written_at": "2026-01-01T00:00:00Z",
            "operator_escalation_ref": None,
            "emitted_event_ids_json": "[]",
        }
        bridge, _conn = _make_mock_bridge(fetchrow_result=row)
        store = PostgresRecoveryOutcomeStore(dsn="postgresql://mock", bridge=bridge)
        outcome = await store.latest_for_run("run-2")
        assert outcome is not None
        assert outcome.emitted_event_ids == []


@pytest.mark.unit
class TestPostgresRecoveryOutcomeStoreWriteOutcome:
    """Verify write_outcome() protocol contract."""

    @pytest.mark.asyncio
    async def test_write_outcome_does_not_raise_with_mock_pool(self):
        """write_outcome() completes without raising when the pool is mocked."""
        from agent_kernel.kernel.persistence.pg_recovery_outcome_store import (
            PostgresRecoveryOutcomeStore,
        )

        bridge, _conn = _make_mock_bridge(execute_result=None)
        store = PostgresRecoveryOutcomeStore(dsn="postgresql://mock", bridge=bridge)
        outcome = _make_recovery_outcome("run-42")
        # Should not raise
        await store.write_outcome(outcome)
        # execute was called (INSERT)
        _conn.execute.assert_called()
