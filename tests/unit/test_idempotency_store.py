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

        # Verify by replaying — record should reflect completed status.
        outcome, record = store.reserve_or_replay("t1", "key-001", "h1", "run-999")
        assert outcome == "replayed"
        assert record.status == "completed"
        assert record.response_snapshot == '{"result": "ok"}'


class TestMarkFailed:
    def test_mark_failed_updates_status(self, store):
        store.reserve_or_replay("t1", "key-fail", "hf", "run-fail")
        store.mark_failed("t1", "key-fail")

        outcome, record = store.reserve_or_replay("t1", "key-fail", "hf", "run-x")
        assert outcome == "replayed"
        assert record.status == "failed"


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
