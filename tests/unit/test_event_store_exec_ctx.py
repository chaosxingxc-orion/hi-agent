"""Unit tests for SQLiteEventStore.append with exec_ctx.

Layer 1 — Unit tests; SQLite in-memory (no external mocks).
"""

from __future__ import annotations

import pytest
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.server.event_store import SQLiteEventStore, StoredEvent


@pytest.fixture()
def store():
    """Fresh in-memory SQLiteEventStore."""
    s = SQLiteEventStore(db_path=":memory:")
    yield s
    s.close()


def _make_event(**kwargs) -> StoredEvent:
    defaults: dict = {
        "event_id": "evt-001",
        "run_id": "run-001",
        "sequence": 1,
        "event_type": "test_event",
        "payload_json": "{}",
        "tenant_id": "",
        "user_id": "__legacy__",
        "session_id": "__legacy__",
    }
    defaults.update(kwargs)
    return StoredEvent(**defaults)


class TestAppendWithExecCtx:
    def test_exec_ctx_spine_overwrites_event_spine(self, store):
        """exec_ctx fields override the event's own tenant/user/session/run_id."""
        ctx = RunExecutionContext(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            run_id="run-ctx-001",
        )
        event = _make_event(
            event_id="evt-ctx-001",
            run_id="run-original",
            tenant_id="",
            user_id="__legacy__",
            session_id="__legacy__",
        )
        store.append(event, exec_ctx=ctx)

        rows = store.list_since("run-ctx-001", since_sequence=0)
        assert len(rows) == 1
        stored = rows[0]
        assert stored.tenant_id == "t1"
        assert stored.user_id == "u1"
        assert stored.session_id == "s1"
        assert stored.run_id == "run-ctx-001"

    def test_exec_ctx_none_uses_event_fields(self, store):
        """When exec_ctx is None, the event's own fields are stored unchanged."""
        event = _make_event(
            event_id="evt-no-ctx",
            run_id="run-no-ctx",
            tenant_id="t-original",
            user_id="u-original",
            session_id="s-original",
        )
        store.append(event, exec_ctx=None)

        rows = store.list_since("run-no-ctx", since_sequence=0)
        assert len(rows) == 1
        stored = rows[0]
        assert stored.tenant_id == "t-original"
        assert stored.user_id == "u-original"
        assert stored.session_id == "s-original"

    def test_exec_ctx_empty_fields_do_not_overwrite_event_spine(self, store):
        """exec_ctx fields that are empty string keep the event's existing values."""
        ctx = RunExecutionContext(
            tenant_id="",   # empty
            user_id="u-ctx",
            session_id="",  # empty
            run_id="run-partial",
        )
        event = _make_event(
            event_id="evt-partial",
            run_id="run-partial",
            tenant_id="t-evt",
            user_id="u-evt",
            session_id="s-evt",
        )
        store.append(event, exec_ctx=ctx)

        rows = store.list_since("run-partial", since_sequence=0)
        assert len(rows) == 1
        stored = rows[0]
        # tenant_id empty in ctx → event's value retained
        assert stored.tenant_id == "t-evt"
        # user_id set in ctx → ctx wins
        assert stored.user_id == "u-ctx"
        # session_id empty in ctx → event's value retained
        assert stored.session_id == "s-evt"
