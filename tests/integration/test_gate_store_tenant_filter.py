"""Track W2-A: SQLiteGateStore / InMemoryGateAPI read-path tenant filtering.

Verifies that ``list_pending(tenant_id=...)`` and ``get_gate(gate_ref,
tenant_id=...)`` scope results to the requested tenant — no cross-tenant
leakage from the shared SQLite gate pool, and cross-tenant fetches raise
the same ``ValueError("gate ... not found")`` as a missing row (preserves
object-level 404 semantics).

Layer 2 — Integration: real SQLiteGateStore against tmp_path.  No mocks.
"""

from __future__ import annotations

import pytest
from hi_agent.management.gate_api import InMemoryGateAPI
from hi_agent.management.gate_context import build_gate_context
from hi_agent.management.gate_store import SQLiteGateStore

pytestmark = pytest.mark.integration


def _make_context(gate_ref: str):
    return build_gate_context(
        gate_ref=gate_ref,
        run_id=f"run-{gate_ref}",
        stage_id="stage-1",
        branch_id="branch-1",
        submitter="alice",
    )


def test_list_pending_filters_by_tenant_id(tmp_path):
    """list_pending(tenant_id='tenant-A') returns only A's gates from a 2-tenant DB."""
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    try:
        store.create_gate(
            context=_make_context("g-a1"),
            tenant_id="tenant-A",
            user_id="user-a",
            session_id="sess-a",
            project_id="proj-a",
        )
        store.create_gate(
            context=_make_context("g-a2"),
            tenant_id="tenant-A",
            user_id="user-a",
            session_id="sess-a",
            project_id="proj-a",
        )
        store.create_gate(
            context=_make_context("g-b1"),
            tenant_id="tenant-B",
            user_id="user-b",
            session_id="sess-b",
            project_id="proj-b",
        )

        a_gates = store.list_pending(tenant_id="tenant-A")
        b_gates = store.list_pending(tenant_id="tenant-B")

        assert {r.context.gate_ref for r in a_gates} == {"g-a1", "g-a2"}
        assert {r.context.gate_ref for r in b_gates} == {"g-b1"}
        assert all(r.context.tenant_id == "tenant-A" for r in a_gates)
        assert all(r.context.tenant_id == "tenant-B" for r in b_gates)

        # Legacy unscoped call still returns the full pool.
        all_pending = store.list_pending()
        assert {r.context.gate_ref for r in all_pending} == {"g-a1", "g-a2", "g-b1"}

        # InMemoryGateAPI parity.
        api = InMemoryGateAPI()
        api.create_gate(context=_make_context("m-a"), tenant_id="tenant-A")
        api.create_gate(context=_make_context("m-b"), tenant_id="tenant-B")
        assert {r.context.gate_ref for r in api.list_pending(tenant_id="tenant-A")} == {"m-a"}
        assert {r.context.gate_ref for r in api.list_pending(tenant_id="tenant-B")} == {"m-b"}
    finally:
        store.close()


def test_get_gate_cross_tenant_raises_not_found(tmp_path):
    """get_gate(gate_ref, tenant_id='tenant-B') raises ValueError for a Tenant-A gate."""
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    try:
        store.create_gate(
            context=_make_context("g-a"),
            tenant_id="tenant-A",
            user_id="user-a",
            session_id="sess-a",
            project_id="proj-a",
        )

        # Tenant A can fetch its own gate.
        record = store.get_gate("g-a", tenant_id="tenant-A")
        assert record.context.tenant_id == "tenant-A"

        # Tenant B sees the same shape as a missing gate (object-level 404).
        with pytest.raises(ValueError, match="gate g-a not found"):
            store.get_gate("g-a", tenant_id="tenant-B")

        # Sanity: legacy unscoped call still fetches it.
        legacy = store.get_gate("g-a")
        assert legacy.context.gate_ref == "g-a"

        # InMemoryGateAPI parity.
        api = InMemoryGateAPI()
        api.create_gate(context=_make_context("mem-a"), tenant_id="tenant-A")
        assert api.get_gate("mem-a", tenant_id="tenant-A").context.tenant_id == "tenant-A"
        with pytest.raises(ValueError, match="gate mem-a not found"):
            api.get_gate("mem-a", tenant_id="tenant-B")
    finally:
        store.close()
