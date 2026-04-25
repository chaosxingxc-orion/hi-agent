"""Unit tests for IdempotencyStore.

Layer 1 — Unit tests; SQLite is used directly (no external mocks).
"""

from __future__ import annotations

import pytest
from hi_agent.server.idempotency import IdempotencyStore, _hash_payload


@pytest.fixture()
def store(tmp_path):
    """Fresh IdempotencyStore backed by a temporary SQLite file."""
    s = IdempotencyStore(db_path=tmp_path / "idempotency.db")
    yield s
    s.close()


class TestReserveOrReplay:
    def test_first_call_returns_created(self, store):
        outcome, record = store.reserve_or_replay(
            tenant_id="t1",
            idempotency_key="key-001",
            request_hash="abc123",
            run_id="run-001",
        )
        assert outcome == "created"
        assert record.run_id == "run-001"
        assert record.status == "pending"
        assert record.tenant_id == "t1"
        assert record.idempotency_key == "key-001"

    def test_same_key_same_hash_returns_replayed(self, store):
        store.reserve_or_replay("t1", "key-001", "abc123", "run-001")

        outcome, record = store.reserve_or_replay("t1", "key-001", "abc123", "run-002")

        assert outcome == "replayed"
        # Must return the ORIGINAL run_id, not the new candidate.
        assert record.run_id == "run-001"

    def test_same_key_different_hash_returns_conflict(self, store):
        store.reserve_or_replay("t1", "key-001", "hash-A", "run-001")

        outcome, record = store.reserve_or_replay("t1", "key-001", "hash-B", "run-002")

        assert outcome == "conflict"
        assert record.run_id == "run-001"  # existing record returned

    def test_different_tenants_share_key_without_collision(self, store):
        outcome_a, rec_a = store.reserve_or_replay("tenant-A", "shared-key", "hashX", "run-A")
        outcome_b, rec_b = store.reserve_or_replay("tenant-B", "shared-key", "hashX", "run-B")

        assert outcome_a == "created"
        assert outcome_b == "created"
        assert rec_a.run_id == "run-A"
        assert rec_b.run_id == "run-B"

    def test_second_replay_still_returns_same_run_id(self, store):
        store.reserve_or_replay("t1", "key-multi", "h1", "run-orig")

        for _ in range(3):
            outcome, record = store.reserve_or_replay("t1", "key-multi", "h1", "run-other")
            assert outcome == "replayed"
            assert record.run_id == "run-orig"


class TestMarkComplete:
    def test_mark_complete_updates_status_and_snapshot(self, store):
        store.reserve_or_replay("t1", "key-001", "h1", "run-001")
        store.mark_complete("t1", "key-001", '{"result": "ok"}')

        # Verify by replaying — record should reflect succeeded status (RO-7: default terminal).
        outcome, record = store.reserve_or_replay("t1", "key-001", "h1", "run-999")
        assert outcome == "replayed"
        assert record.status == "succeeded"  # RO-7: default terminal is now "succeeded"
        assert record.response_snapshot == '{"result": "ok"}'


class TestMarkFailed:
    def test_mark_failed_updates_status(self, store):
        store.reserve_or_replay("t1", "key-fail", "hf", "run-fail")
        store.mark_failed("t1", "key-fail")

        outcome, record = store.reserve_or_replay("t1", "key-fail", "hf", "run-x")
        assert outcome == "replayed"
        assert record.status == "failed"


class TestSpineFields:
    """RO-2: project_id, user_id, session_id are persisted in new rows."""

    def test_new_record_stores_spine_fields(self, store):
        outcome, record = store.reserve_or_replay(
            tenant_id="t1",
            idempotency_key="spine-001",
            request_hash="h1",
            run_id="run-001",
            project_id="proj-abc",
            user_id="user-xyz",
            session_id="sess-123",
        )
        assert outcome == "created"
        assert record.project_id == "proj-abc"
        assert record.user_id == "user-xyz"
        assert record.session_id == "sess-123"

    def test_replayed_record_returns_original_spine_fields(self, store):
        store.reserve_or_replay(
            tenant_id="t1",
            idempotency_key="spine-002",
            request_hash="h2",
            run_id="run-original",
            project_id="proj-orig",
            user_id="user-orig",
            session_id="sess-orig",
        )
        outcome, record = store.reserve_or_replay(
            tenant_id="t1",
            idempotency_key="spine-002",
            request_hash="h2",
            run_id="run-retry",
            project_id="proj-retry",
            user_id="user-retry",
            session_id="sess-retry",
        )
        assert outcome == "replayed"
        # Original record fields are preserved.
        assert record.project_id == "proj-orig"
        assert record.user_id == "user-orig"
        assert record.session_id == "sess-orig"

    def test_spine_fields_default_to_empty_string(self, store):
        outcome, record = store.reserve_or_replay(
            tenant_id="t2",
            idempotency_key="spine-003",
            request_hash="h3",
            run_id="run-003",
        )
        assert outcome == "created"
        assert record.project_id == ""
        assert record.user_id == ""
        assert record.session_id == ""

    def test_mark_complete_with_terminal_state(self, store):
        """RO-7: mark_complete stores the exact terminal_state in status."""
        store.reserve_or_replay("t1", "tc-001", "h1", "run-001")
        store.mark_complete("t1", "tc-001", '{"ok": true}', terminal_state="cancelled")

        outcome, record = store.reserve_or_replay("t1", "tc-001", "h1", "run-999")
        assert outcome == "replayed"
        assert record.status == "cancelled"

    def test_mark_complete_defaults_to_succeeded(self, store):
        store.reserve_or_replay("t1", "tc-002", "h2", "run-002")
        store.mark_complete("t1", "tc-002", '{"ok": true}')

        _, record = store.reserve_or_replay("t1", "tc-002", "h2", "run-999")
        assert record.status == "succeeded"

    def test_existing_db_migration_adds_spine_columns(self, tmp_path):
        """RO-2: _migrate() adds missing columns to pre-existing databases."""
        import sqlite3

        db_file = tmp_path / "legacy.db"
        # Create a legacy schema without spine columns.
        conn = sqlite3.connect(str(db_file))
        conn.execute(
            "CREATE TABLE idempotency_records ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "tenant_id TEXT NOT NULL, "
            "idempotency_key TEXT NOT NULL, "
            "request_hash TEXT NOT NULL, "
            "run_id TEXT NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'pending', "
            "response_snapshot TEXT NOT NULL DEFAULT '', "
            "created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL, "
            "expires_at REAL NOT NULL, "
            "UNIQUE (tenant_id, idempotency_key)"
            ")"
        )
        conn.commit()
        conn.close()

        # Opening IdempotencyStore should run _migrate() without error.
        store2 = IdempotencyStore(db_path=db_file)
        outcome, record = store2.reserve_or_replay(
            tenant_id="t1",
            idempotency_key="migrated-key",
            request_hash="h1",
            run_id="run-001",
            project_id="proj-migrated",
        )
        assert outcome == "created"
        assert record.project_id == "proj-migrated"
        store2.close()


class TestHashPayload:
    def test_hash_is_deterministic(self):
        payload = {"goal": "analyse", "priority": 1, "tags": ["a", "b"]}
        assert _hash_payload(payload) == _hash_payload(payload)

    def test_hash_differs_for_different_payloads(self):
        assert _hash_payload({"a": 1}) != _hash_payload({"a": 2})

    def test_hash_is_order_independent(self):
        p1 = {"b": 2, "a": 1}
        p2 = {"a": 1, "b": 2}
        assert _hash_payload(p1) == _hash_payload(p2)
