"""Integration: GateStore persists gate decisions across simulated restarts.

Layer 2 — Integration: real SQLite file on disk; close the store, open a new
instance on the same path, assert that gate decisions written before close
are present and tenant-scoped after reopening.

This satisfies the Track X 4th store restart-survival requirement (CL1).
"""

from __future__ import annotations

import pytest
from hi_agent.management.gate_api import GateStatus
from hi_agent.management.gate_context import GateContext
from hi_agent.management.gate_store import SQLiteGateStore


def _make_context(gate_ref: str, *, tenant_id: str = "tenant-test") -> GateContext:
    return GateContext(
        gate_ref=gate_ref,
        run_id="run-restart-001",
        stage_id="stage-1",
        branch_id="branch-1",
        submitter="test-submitter",
        tenant_id=tenant_id,
    )


@pytest.mark.serial
def test_gate_store_survives_restart(tmp_path):
    """Gate decision written before close is readable from a new store instance.

    Write a gate, close the store, open a fresh instance on the same DB path,
    verify the decision persists with correct status and metadata.
    """
    db = tmp_path / "gates_restart.db"
    store1 = SQLiteGateStore(db)
    ctx = _make_context("gate-restart-001")
    store1.create_gate(context=ctx, timeout_seconds=300.0)
    # Resolve the gate before closing.
    store1.resolve(gate_ref="gate-restart-001", action="approve", approver="admin")
    store1.close()

    # Simulate process restart by constructing a new store instance.
    store2 = SQLiteGateStore(db)
    record = store2.get_gate("gate-restart-001", internal_unscoped=True)
    assert record.status == GateStatus.APPROVED
    assert record.resolution_by == "admin"
    assert record.context.gate_ref == "gate-restart-001"
    assert record.context.run_id == "run-restart-001"
    store2.close()


@pytest.mark.serial
def test_gate_store_restart_preserves_tenant_scope(tmp_path):
    """Tenant isolation holds across a store close-reopen cycle.

    Gate created under tenant-A must not be visible under tenant-B after
    restart, and must remain accessible under tenant-A.
    """
    db = tmp_path / "gates_tenant_restart.db"
    store1 = SQLiteGateStore(db)
    ctx_a = _make_context("gate-tenant-a-001", tenant_id="tenant-A")
    ctx_b = _make_context("gate-tenant-b-001", tenant_id="tenant-B")
    store1.create_gate(context=ctx_a, timeout_seconds=300.0)
    store1.create_gate(context=ctx_b, timeout_seconds=300.0)
    store1.close()

    # Reopen and assert per-tenant isolation still holds.
    store2 = SQLiteGateStore(db)

    # tenant-A can read its own gate.
    record_a = store2.get_gate("gate-tenant-a-001", tenant_id="tenant-A")
    assert record_a.status == GateStatus.PENDING
    assert record_a.context.tenant_id == "tenant-A"

    # tenant-B cannot read tenant-A's gate.
    with pytest.raises(ValueError, match="not found"):
        store2.get_gate("gate-tenant-a-001", tenant_id="tenant-B")

    # tenant-B can read its own gate.
    record_b = store2.get_gate("gate-tenant-b-001", tenant_id="tenant-B")
    assert record_b.status == GateStatus.PENDING
    assert record_b.context.tenant_id == "tenant-B"

    store2.close()
