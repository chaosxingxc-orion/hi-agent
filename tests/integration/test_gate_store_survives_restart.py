"""Integration: SQLiteGateStore persists gates across restarts.

Verifies that a gate created in one store instance is readable and
resolvable from a fresh store instance pointing at the same DB file.
This confirms durability of the SQLite WAL-backed store (P3.2).
"""

from __future__ import annotations

import pytest
from hi_agent.management.gate_api import GateStatus
from hi_agent.management.gate_context import build_gate_context
from hi_agent.management.gate_store import SQLiteGateStore


def _make_context(gate_ref: str):
    return build_gate_context(
        gate_ref=gate_ref,
        run_id="run-test-001",
        stage_id="stage-1",
        branch_id="branch-1",
        submitter="test-submitter",
    )


@pytest.mark.serial
def test_pending_gate_survives_restart(tmp_path):
    """Gate created in store1 is visible with PENDING status in store2."""
    db = tmp_path / "gates.db"
    store1 = SQLiteGateStore(db)
    ctx = _make_context("gate-001")
    store1.create_gate(context=ctx, timeout_seconds=300.0)
    store1.close()

    # Simulate process restart by opening a new store instance.
    store2 = SQLiteGateStore(db)
    record = store2.get_gate("gate-001")
    assert record.status == GateStatus.PENDING
    assert record.context.gate_ref == "gate-001"
    assert record.context.run_id == "run-test-001"
    store2.close()


@pytest.mark.serial
def test_approve_after_restart(tmp_path):
    """Gate resolved APPROVED in store2 reflects correct status."""
    db = tmp_path / "gates.db"
    store1 = SQLiteGateStore(db)
    ctx = _make_context("gate-002")
    store1.create_gate(context=ctx, timeout_seconds=300.0)
    store1.close()

    store2 = SQLiteGateStore(db)
    resolved = store2.resolve(gate_ref="gate-002", action="approve", approver="admin")
    assert resolved.status == GateStatus.APPROVED
    assert resolved.resolution_by == "admin"
    store2.close()


@pytest.mark.serial
def test_list_pending_after_mixed_restart(tmp_path):
    """Only pending gates appear in list_pending after one is resolved."""
    db = tmp_path / "gates.db"
    store1 = SQLiteGateStore(db)
    store1.create_gate(context=_make_context("gate-003"), timeout_seconds=300.0)
    store1.create_gate(context=_make_context("gate-004"), timeout_seconds=300.0)
    store1.close()

    store2 = SQLiteGateStore(db)
    store2.resolve(gate_ref="gate-003", action="reject", approver="admin")
    pending = store2.list_pending()
    assert len(pending) == 1
    assert pending[0].context.gate_ref == "gate-004"
    store2.close()
