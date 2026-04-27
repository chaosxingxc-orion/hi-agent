"""Unit tests for PostgresKernelRuntimeEventLog using a mock AsyncPGBridge.

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


def _make_mock_bridge(
    fetchrow_result=None,
    fetchval_result=None,
    fetch_result=None,
    execute_result=None,
):
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
    conn.fetchval = AsyncMock(return_value=fetchval_result)
    conn.fetch = AsyncMock(return_value=fetch_result if fetch_result is not None else [])
    conn.execute = AsyncMock(return_value=execute_result)

    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction.return_value = tx_ctx

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx

    bridge.pool = pool
    return bridge, conn


def _make_runtime_event(run_id: str = "run-1", offset: int = 1):
    """Build a minimal RuntimeEvent for testing."""
    from agent_kernel.kernel.contracts import RuntimeEvent

    return RuntimeEvent(
        run_id=run_id,
        event_id=f"evt-{offset}",
        commit_offset=offset,
        event_type="task.started",
        event_class="fact",
        event_authority="authoritative_fact",
        ordering_key=f"ok-{offset}",
        wake_policy="wake_actor",
        created_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostgresKernelRuntimeEventLogInstantiation:
    """Verify the event log can be constructed with a pre-built bridge."""

    def test_instantiated_with_mock_bridge(self):
        """Event log accepts a pre-built bridge without touching a real PostgreSQL server."""
        from agent_kernel.kernel.persistence.pg_event_log import (
            PostgresKernelRuntimeEventLog,
        )

        bridge, _conn = _make_mock_bridge()
        log = PostgresKernelRuntimeEventLog(dsn="postgresql://mock", bridge=bridge)
        assert log is not None

    def test_owns_bridge_flag_false_when_bridge_injected(self):
        """_own_bridge is False when a bridge is injected."""
        from agent_kernel.kernel.persistence.pg_event_log import (
            PostgresKernelRuntimeEventLog,
        )

        bridge, _conn = _make_mock_bridge()
        log = PostgresKernelRuntimeEventLog(dsn="postgresql://mock", bridge=bridge)
        assert log._own_bridge is False


@pytest.mark.unit
class TestPostgresKernelRuntimeEventLogLoad:
    """Verify load() protocol contract."""

    @pytest.mark.asyncio
    async def test_load_returns_empty_list_for_unknown_run(self):
        """load() returns [] when no events exist for a run_id."""
        from agent_kernel.kernel.persistence.pg_event_log import (
            PostgresKernelRuntimeEventLog,
        )

        bridge, _conn = _make_mock_bridge(fetch_result=[])
        log = PostgresKernelRuntimeEventLog(dsn="postgresql://mock", bridge=bridge)
        events = await log.load("unknown-run", after_offset=0)
        assert events == []

    @pytest.mark.asyncio
    async def test_max_offset_returns_zero_for_unknown_run(self):
        """max_offset() returns 0 when no events exist for a run_id."""
        from agent_kernel.kernel.persistence.pg_event_log import (
            PostgresKernelRuntimeEventLog,
        )

        bridge, _conn = _make_mock_bridge(fetchval_result=0)
        log = PostgresKernelRuntimeEventLog(dsn="postgresql://mock", bridge=bridge)
        offset = await log.max_offset("unknown-run")
        assert offset == 0


@pytest.mark.unit
class TestPostgresKernelRuntimeEventLogReadEvents:
    """Verify read_events() sync protocol contract."""

    def test_read_events_returns_empty_list_for_unknown_run(self):
        """read_events() sync wrapper returns [] for an unknown run_id."""
        from agent_kernel.kernel.persistence.pg_event_log import (
            PostgresKernelRuntimeEventLog,
        )

        bridge, _conn = _make_mock_bridge(fetch_result=[])
        log = PostgresKernelRuntimeEventLog(dsn="postgresql://mock", bridge=bridge)
        events = log.read_events("unknown-run")
        assert events == []
