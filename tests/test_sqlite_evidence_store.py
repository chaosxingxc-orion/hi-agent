"""Tests for SqliteEvidenceStore."""

from __future__ import annotations

import threading

import pytest
from hi_agent.harness.contracts import EvidenceRecord
from hi_agent.harness.evidence_store import (
    EvidenceStoreProtocol,
    SqliteEvidenceStore,
)


def _make_record(
    ref: str = "ev-1",
    action_id: str = "act-1",
    evidence_type: str = "output",
    content: dict | None = None,
    timestamp: str = "2026-01-01T00:00:00Z",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_ref=ref,
        action_id=action_id,
        evidence_type=evidence_type,
        content=content or {"key": "value"},
        timestamp=timestamp,
    )


class TestSqliteEvidenceStore:
    """SqliteEvidenceStore tests."""

    def test_store_and_retrieve(self, tmp_path):
        db = tmp_path / "ev.db"
        store = SqliteEvidenceStore(db_path=db)
        rec = _make_record()
        ref = store.store(rec)
        assert ref == "ev-1"
        got = store.get("ev-1")
        assert got is not None
        assert got.evidence_ref == "ev-1"
        assert got.action_id == "act-1"
        assert got.content == {"key": "value"}
        store.close()

    def test_get_by_action(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        store.store(_make_record(ref="ev-1", action_id="act-A"))
        store.store(_make_record(ref="ev-2", action_id="act-A"))
        store.store(_make_record(ref="ev-3", action_id="act-B"))
        results = store.get_by_action("act-A")
        assert len(results) == 2
        assert {r.evidence_ref for r in results} == {"ev-1", "ev-2"}
        store.close()

    def test_persistence_across_instances(self, tmp_path):
        db = tmp_path / "ev.db"
        store1 = SqliteEvidenceStore(db_path=db)
        store1.store(_make_record(ref="ev-p", action_id="act-1"))
        store1.close()

        store2 = SqliteEvidenceStore(db_path=db)
        got = store2.get("ev-p")
        assert got is not None
        assert got.evidence_ref == "ev-p"
        assert store2.count() == 1
        store2.close()

    def test_concurrent_writes(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        errors = []

        def writer(idx: int):
            try:
                store.store(_make_record(ref=f"ev-{idx}", action_id=f"act-{idx}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert store.count() == 4
        store.close()

    def test_protocol_conformance(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        assert isinstance(store, EvidenceStoreProtocol)
        store.close()

    def test_upsert(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        store.store(_make_record(ref="ev-u", content={"v": 1}))
        store.store(_make_record(ref="ev-u", content={"v": 2}))
        got = store.get("ev-u")
        assert got is not None
        assert got.content == {"v": 2}
        assert store.count() == 1
        store.close()

    def test_empty_store(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        assert store.get("nonexistent") is None
        assert store.get_by_action("nope") == []
        assert store.count() == 0
        store.close()

    def test_count(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        for i in range(5):
            store.store(_make_record(ref=f"ev-{i}", action_id="act-1"))
        assert store.count() == 5
        store.close()

    def test_empty_ref_raises(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        with pytest.raises(ValueError, match="evidence_ref must not be empty"):
            store.store(_make_record(ref=""))
        store.close()


class TestStoreManyAndTransaction:
    """Tests for SqliteEvidenceStore.store_many() and transaction()."""

    def test_store_many_persists_all(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        records = [_make_record(ref=f"ev-{i}", action_id="act-1") for i in range(5)]
        store.store_many(records)
        assert store.count() == 5
        store.close()

    def test_store_many_atomic_rollback(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        store.store(_make_record(ref="ev-pre"))
        # One record with empty ref should cause full batch rollback
        bad_batch = [
            _make_record(ref="ev-a"),
            _make_record(ref=""),  # invalid
            _make_record(ref="ev-b"),
        ]
        with pytest.raises(ValueError):
            store.store_many(bad_batch)
        # Only the pre-existing record survives
        assert store.count() == 1
        store.close()

    def test_store_many_empty_list(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        store.store_many([])
        assert store.count() == 0
        store.close()

    def test_store_many_upsert(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        store.store(_make_record(ref="ev-x", content={"v": 1}))
        store.store_many([_make_record(ref="ev-x", content={"v": 99})])
        got = store.get("ev-x")
        assert got is not None
        assert got.content == {"v": 99}
        assert store.count() == 1
        store.close()

    def test_transaction_commit(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        with store.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO evidence "
                "(evidence_ref, action_id, evidence_type, content, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                ("ev-tx", "act-1", "output", '{"k": 1}', "2026-01-01T00:00:00Z"),
            )
        assert store.count() == 1
        store.close()

    def test_transaction_rollback_on_exception(self, tmp_path):
        store = SqliteEvidenceStore(db_path=tmp_path / "ev.db")
        try:
            with store.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO evidence "
                    "(evidence_ref, action_id, evidence_type, content, timestamp) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("ev-rb", "act-1", "output", "{}", "2026-01-01T00:00:00Z"),
                )
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass
        assert store.count() == 0
        store.close()
