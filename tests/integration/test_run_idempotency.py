"""Integration tests for run idempotency through RunManager.

Layer 2 — Integration tests; real RunManager + real SQLite stores wired
together, no internal mocking.
"""

from __future__ import annotations

import pytest

from hi_agent.server.idempotency import IdempotencyStore, _hash_payload
from hi_agent.server.run_manager import RunManager
from hi_agent.server.run_store import SQLiteRunStore


@pytest.fixture()
def idempotency_store(tmp_path):
    s = IdempotencyStore(db_path=tmp_path / "idempotency.db")
    yield s
    s.close()


@pytest.fixture()
def run_store(tmp_path):
    s = SQLiteRunStore(db_path=tmp_path / "runs.db")
    yield s
    s.close()


@pytest.fixture()
def manager(idempotency_store, run_store):
    return RunManager(
        max_concurrent=2,
        idempotency_store=idempotency_store,
        run_store=run_store,
    )


class TestIdempotentCreateRun:
    def test_same_key_same_payload_returns_same_run_id(self, manager):
        payload = {"goal": "analyse revenue", "idempotency_key": "client-key-1"}

        run_id_1 = manager.create_run(dict(payload))
        run_id_2 = manager.create_run(dict(payload))

        assert run_id_1 == run_id_2

    def test_same_key_different_payload_raises_conflict(self, manager):
        payload_a = {"goal": "analyse revenue", "idempotency_key": "client-key-2"}
        payload_b = {"goal": "analyse costs", "idempotency_key": "client-key-2"}

        manager.create_run(dict(payload_a))

        with pytest.raises(ValueError, match="idempotency_conflict"):
            manager.create_run(dict(payload_b))

    def test_different_keys_produce_distinct_run_ids(self, manager):
        payload_a = {"goal": "task A", "idempotency_key": "key-A"}
        payload_b = {"goal": "task B", "idempotency_key": "key-B"}

        run_id_a = manager.create_run(dict(payload_a))
        run_id_b = manager.create_run(dict(payload_b))

        assert run_id_a != run_id_b

    def test_no_idempotency_key_falls_through_to_normal_path(self, manager):
        payload = {"goal": "no-key task"}

        run_id_1 = manager.create_run(dict(payload))
        run_id_2 = manager.create_run(dict(payload))

        # Without idempotency_key, two separate run_ids are created.
        assert run_id_1 != run_id_2

    def test_run_persisted_to_run_store_on_creation(self, manager, run_store):
        payload = {"goal": "persist me", "idempotency_key": "persist-key"}

        run_id = manager.create_run(dict(payload))
        record = run_store.get(run_id)

        assert record is not None
        assert record.run_id == run_id
        assert record.status == "queued"

    def test_replayed_run_not_duplicated_in_run_store(self, manager, run_store):
        payload = {"goal": "dedup test", "idempotency_key": "dedup-key"}

        run_id = manager.create_run(dict(payload))
        manager.create_run(dict(payload))  # replay

        # Only one record in the store.
        records = run_store.list_by_tenant("default")
        matching = [r for r in records if r.run_id == run_id]
        assert len(matching) == 1


class TestWithoutStores:
    def test_manager_without_stores_behaves_as_before(self):
        """No stores injected — all existing behaviour is unchanged."""
        plain_manager = RunManager(max_concurrent=2)

        run_id_1 = plain_manager.create_run({"goal": "test"})
        run_id_2 = plain_manager.create_run({"goal": "test"})

        # Two separate run_ids without idempotency.
        assert run_id_1 != run_id_2
        assert plain_manager.get_run(run_id_1) is not None
        assert plain_manager.get_run(run_id_2) is not None
