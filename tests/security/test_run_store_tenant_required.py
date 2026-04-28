"""Security tests for SQLiteRunStore tenant-scoped access.

Layer 1 — Unit tests; SQLite is used directly (no mocks).

Verifies:
- get_for_tenant(run_id, None) raises ValueError
- get_for_tenant("nonexistent", "tenant1") returns None (no cross-tenant leak)
- A run created for tenant-A is not visible to tenant-B via get_for_tenant
"""
from __future__ import annotations

import time

import pytest
from hi_agent.server.run_store import RunRecord, SQLiteRunStore


def _make_record(run_id: str, tenant_id: str) -> RunRecord:
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


class TestGetForTenant:
    def test_none_workspace_raises_value_error(self, store):
        """get_for_tenant must raise ValueError when workspace is None."""
        store.upsert(_make_record("run-001", "tenant-A"))
        with pytest.raises(ValueError, match="requires a non-None workspace"):
            store.get_for_tenant("run-001", None)

    def test_nonexistent_run_returns_none(self, store):
        """get_for_tenant returns None for a run_id that does not exist."""
        result = store.get_for_tenant("nonexistent-run", "tenant1")
        assert result is None

    def test_cross_tenant_isolation(self, store):
        """A run owned by tenant-A is not returned when queried with tenant-B."""
        store.upsert(_make_record("run-001", "tenant-A"))
        result = store.get_for_tenant("run-001", "tenant-B")
        assert result is None

    def test_correct_tenant_returns_record(self, store):
        """get_for_tenant returns the record when workspace matches the run's tenant."""
        store.upsert(_make_record("run-001", "tenant-A"))
        result = store.get_for_tenant("run-001", "tenant-A")
        assert result is not None
        assert result.run_id == "run-001"
        assert result.tenant_id == "tenant-A"


class TestGetWithWorkspace:
    def test_get_without_workspace_is_backward_compat(self, store):
        """get() without workspace still works for process-internal callers."""
        store.upsert(_make_record("run-002", "tenant-Z"))
        result = store.get("run-002")
        assert result is not None
        assert result.run_id == "run-002"

    def test_get_with_workspace_filters_by_tenant(self, store):
        """get(workspace=) enforces tenant filter."""
        store.upsert(_make_record("run-003", "tenant-X"))
        # Correct tenant
        assert store.get("run-003", workspace="tenant-X") is not None
        # Wrong tenant
        assert store.get("run-003", workspace="tenant-Y") is None
