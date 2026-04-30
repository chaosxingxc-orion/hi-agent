"""Integration: LongRunningOpStore persists handles across restarts.

Verifies that an OpHandle written by one store instance is readable from a
fresh instance pointing at the same SQLite file (Rule 2 RO track: durable-store
changes require restart-survival test).
"""

from __future__ import annotations

import time

import pytest
from hi_agent.operations.op_store import LongRunningOpStore, OpStatus


@pytest.mark.serial
def test_op_handle_survives_restart(tmp_path):
    """OpHandle created in store1 is readable from store2 (restart simulation)."""
    db = tmp_path / "ops.db"

    store1 = LongRunningOpStore(db_path=db)
    handle = store1.create(
        op_id="op-001",
        backend="batch",
        external_id="ext-001",
        submitted_at=time.time(),
        tenant_id="t-test",
        run_id="run-001",
        project_id="proj-001",
    )
    assert handle.op_id == "op-001"
    # No explicit close needed — LongRunningOpStore opens per call.

    store2 = LongRunningOpStore(db_path=db)
    result = store2.get("op-001")
    assert result is not None, "OpHandle not found after restart"
    assert result.tenant_id == "t-test"
    assert result.run_id == "run-001"
    assert result.project_id == "proj-001"
    assert result.status == OpStatus.PENDING


@pytest.mark.serial
def test_op_status_update_survives_restart(tmp_path):
    """Status update written in store1 is reflected in store2."""
    db = tmp_path / "ops_status.db"

    store1 = LongRunningOpStore(db_path=db)
    store1.create(
        op_id="op-002",
        backend="batch",
        external_id="ext-002",
        submitted_at=time.time(),
        tenant_id="t-test",
        run_id="run-002",
        project_id="proj-002",
    )
    store1.update_status("op-002", OpStatus.SUCCEEDED, completed_at=time.time())

    store2 = LongRunningOpStore(db_path=db)
    result = store2.get("op-002")
    assert result is not None
    assert result.status == OpStatus.SUCCEEDED


@pytest.mark.serial
def test_list_active_ops_survives_restart(tmp_path):
    """list_active returns only pending/running ops from a restarted store."""
    db = tmp_path / "ops_list.db"

    store1 = LongRunningOpStore(db_path=db)
    store1.create(
        op_id="op-003",
        backend="batch",
        external_id="ext-003",
        submitted_at=time.time(),
        tenant_id="t-test",
        run_id="run-003",
        project_id="proj-003",
    )
    store1.create(
        op_id="op-004",
        backend="batch",
        external_id="ext-004",
        submitted_at=time.time(),
        tenant_id="t-test",
        run_id="run-004",
        project_id="proj-004",
    )
    store1.update_status("op-003", OpStatus.FAILED)

    store2 = LongRunningOpStore(db_path=db)
    active = store2.list_active()
    active_ids = {h.op_id for h in active}
    assert "op-004" in active_ids, "Active op missing after restart"
    assert "op-003" not in active_ids, "Completed op wrongly listed as active after restart"
