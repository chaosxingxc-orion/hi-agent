"""Unit tests for IdempotencyStore.reserve_or_replay with exec_ctx.

Layer 1 — Unit tests; SQLite in-process (no external mocks).
"""

from __future__ import annotations

import pytest
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.server.idempotency import IdempotencyStore


@pytest.fixture()
def store(tmp_path):
    """Fresh IdempotencyStore backed by a temporary SQLite file."""
    s = IdempotencyStore(db_path=tmp_path / "idempotency.db")
    yield s
    s.close()


class TestReserveOrReplayWithExecCtx:
    def test_exec_ctx_spine_stored_in_record(self, store):
        """exec_ctx tenant_id/user_id/session_id/project_id override positional args."""
        ctx = RunExecutionContext(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            project_id="p1",
            run_id="run-001",
        )
        outcome, record = store.reserve_or_replay(
            tenant_id="old_tenant",
            idempotency_key="key-ctx-001",
            request_hash="hash-001",
            run_id="run-001",
            exec_ctx=ctx,
        )
        assert outcome == "created"
        assert record.tenant_id == "t1"
        assert record.user_id == "u1"
        assert record.session_id == "s1"
        assert record.project_id == "p1"

    def test_exec_ctx_none_uses_positional_args(self, store):
        """When exec_ctx is None, positional spine args are used unchanged."""
        outcome, record = store.reserve_or_replay(
            tenant_id="tenant-fallback",
            idempotency_key="key-no-ctx",
            request_hash="hash-002",
            run_id="run-002",
            user_id="user-fallback",
            exec_ctx=None,
        )
        assert outcome == "created"
        assert record.tenant_id == "tenant-fallback"
        assert record.user_id == "user-fallback"

    def test_exec_ctx_empty_string_fields_fall_back_to_positional(self, store):
        """exec_ctx fields that are empty string do not override positional args."""
        ctx = RunExecutionContext(
            tenant_id="",   # empty — should fall back
            user_id="u2",
            session_id="",  # empty — should fall back
            project_id="p2",
        )
        outcome, record = store.reserve_or_replay(
            tenant_id="tenant-pos",
            idempotency_key="key-partial-ctx",
            request_hash="hash-003",
            run_id="run-003",
            session_id="session-pos",
            exec_ctx=ctx,
        )
        assert outcome == "created"
        # tenant_id empty in ctx → falls back to positional "tenant-pos"
        assert record.tenant_id == "tenant-pos"
        # user_id set in ctx → wins
        assert record.user_id == "u2"
        # session_id empty in ctx → falls back to positional "session-pos"
        assert record.session_id == "session-pos"
        assert record.project_id == "p2"
