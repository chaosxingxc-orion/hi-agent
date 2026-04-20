"""Unit tests for SQLiteRunStore.

Layer 1 — Unit tests; SQLite is used directly (no external mocks).
"""

from __future__ import annotations

import time

import pytest
from hi_agent.server.run_store import RunRecord, SQLiteRunStore


def _make_record(run_id: str = "run-001", tenant_id: str = "t1") -> RunRecord:
    now = time.time()
    return RunRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        task_contract_json='{"goal": "test"}',
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def store(tmp_path):
    """Fresh SQLiteRunStore backed by a temporary SQLite file."""
    s = SQLiteRunStore(db_path=tmp_path / "runs.db")
    yield s
    s.close()


class TestUpsertGet:
    def test_upsert_then_get_round_trip(self, store):
        rec = _make_record("run-001", "tenant-A")
        store.upsert(rec)

        fetched = store.get("run-001")
        assert fetched is not None
        assert fetched.run_id == "run-001"
        assert fetched.tenant_id == "tenant-A"
        assert fetched.status == "queued"
        assert fetched.cancellation_flag is False

    def test_get_missing_run_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_upsert_overwrites_existing(self, store):
        rec = _make_record("run-001")
        store.upsert(rec)

        updated = _make_record("run-001")
        updated.status = "running"
        store.upsert(updated)

        fetched = store.get("run-001")
        assert fetched is not None
        assert fetched.status == "running"


class TestMarkCancelled:
    def test_mark_cancelled_sets_flag_and_status(self, store):
        store.upsert(_make_record("run-002"))
        store.mark_cancelled("run-002")

        fetched = store.get("run-002")
        assert fetched is not None
        assert fetched.status == "cancelled"
        assert fetched.cancellation_flag is True

    def test_is_cancelled_returns_true_after_cancel(self, store):
        store.upsert(_make_record("run-003"))
        assert store.is_cancelled("run-003") is False

        store.mark_cancelled("run-003")
        assert store.is_cancelled("run-003") is True

    def test_is_cancelled_unknown_run_returns_false(self, store):
        assert store.is_cancelled("ghost-run") is False


class TestMarkComplete:
    def test_mark_complete_updates_status_and_summary(self, store):
        store.upsert(_make_record("run-004"))
        store.mark_complete("run-004", "finished successfully")

        fetched = store.get("run-004")
        assert fetched is not None
        assert fetched.status == "completed"
        assert fetched.result_summary == "finished successfully"


class TestMarkFailed:
    def test_mark_failed_updates_status_and_error(self, store):
        store.upsert(_make_record("run-005"))
        store.mark_failed("run-005", "out of budget")

        fetched = store.get("run-005")
        assert fetched is not None
        assert fetched.status == "failed"
        assert fetched.error_summary == "out of budget"


class TestListByTenant:
    def test_list_by_tenant_returns_only_matching_records(self, store):
        store.upsert(_make_record("run-A1", "tenant-X"))
        store.upsert(_make_record("run-A2", "tenant-X"))
        store.upsert(_make_record("run-B1", "tenant-Y"))

        results = store.list_by_tenant("tenant-X")
        run_ids = {r.run_id for r in results}

        assert run_ids == {"run-A1", "run-A2"}

    def test_list_by_tenant_empty_for_unknown_tenant(self, store):
        store.upsert(_make_record("run-Z1", "tenant-Z"))
        assert store.list_by_tenant("unknown-tenant") == []

    def test_list_by_tenant_isolation(self, store):
        store.upsert(_make_record("run-C1", "alpha"))
        store.upsert(_make_record("run-D1", "beta"))

        alpha = store.list_by_tenant("alpha")
        beta = store.list_by_tenant("beta")

        assert [r.run_id for r in alpha] == ["run-C1"]
        assert [r.run_id for r in beta] == ["run-D1"]
