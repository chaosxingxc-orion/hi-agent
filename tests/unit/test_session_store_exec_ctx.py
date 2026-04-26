"""Unit tests for SessionStore.create with exec_ctx.

Layer 1 — Unit tests; SQLite in-memory (no external mocks).
"""

from __future__ import annotations

import pytest
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.server.session_store import SessionStore


@pytest.fixture()
def store():
    """Initialized in-memory SessionStore."""
    s = SessionStore(db_path=":memory:")
    s.initialize()
    yield s


class TestCreateWithExecCtx:
    def test_exec_ctx_spine_stored_in_session(self, store):
        """exec_ctx tenant_id/user_id override positional arguments."""
        ctx = RunExecutionContext(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
        )
        sid = store.create(
            tenant_id="old_tenant",
            user_id="old_user",
            exec_ctx=ctx,
        )
        record = store.get(sid)
        assert record is not None
        assert record.tenant_id == "t1"
        assert record.user_id == "u1"

    def test_exec_ctx_none_uses_positional_args(self, store):
        """When exec_ctx is None, positional tenant_id/user_id are used."""
        sid = store.create(
            tenant_id="t-positional",
            user_id="u-positional",
            exec_ctx=None,
        )
        record = store.get(sid)
        assert record is not None
        assert record.tenant_id == "t-positional"
        assert record.user_id == "u-positional"

    def test_exec_ctx_empty_fields_fall_back_to_positional(self, store):
        """exec_ctx empty string fields do not override non-empty positional args."""
        ctx = RunExecutionContext(
            tenant_id="",   # empty → fall back
            user_id="u-ctx",
        )
        sid = store.create(
            tenant_id="t-positional",
            user_id="u-positional",
            exec_ctx=ctx,
        )
        record = store.get(sid)
        assert record is not None
        # empty ctx.tenant_id → positional wins
        assert record.tenant_id == "t-positional"
        # non-empty ctx.user_id → ctx wins
        assert record.user_id == "u-ctx"

    def test_create_without_exec_ctx_backward_compat(self, store):
        """Existing callers without exec_ctx kwarg continue to work."""
        sid = store.create("t-compat", "u-compat")
        record = store.get(sid)
        assert record is not None
        assert record.tenant_id == "t-compat"
        assert record.user_id == "u-compat"
