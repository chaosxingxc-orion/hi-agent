"""Track C: SQLiteGateStore persists resolution and has spine columns."""
import pytest
from hi_agent.management.gate_store import SQLiteGateStore
from hi_agent.management.gate_context import GateContext
from hi_agent.management.gate_timeout import GateTimeoutPolicy


def _ctx(gate_ref="g1"):
    return GateContext(
        gate_ref=gate_ref, run_id="r1", stage_id="s1", branch_id="b1",
        submitter="user1", opened_at=0.0,
    )


def test_create_gate_stores_spine(tmp_path):
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    store.create_gate(
        context=_ctx(), tenant_id="t1", user_id="u1", session_id="s1", project_id="p1"
    )
    row = store._con.execute(
        "SELECT tenant_id, user_id, session_id, project_id FROM gates WHERE gate_ref='g1'"
    ).fetchone()
    assert row == ("t1", "u1", "s1", "p1")


def test_resolve_persists_status(tmp_path):
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    store.create_gate(context=_ctx())
    resolved = store.resolve(gate_ref="g1", action="approve", approver="alice")
    assert resolved.status.value == "approved"
    record = store.get_gate("g1")
    assert record.status.value == "approved"


def test_schema_has_spine_columns(tmp_path):
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    cols = {row[1] for row in store._con.execute("PRAGMA table_info(gates)")}
    for col in ("tenant_id", "user_id", "session_id", "resolved_at"):
        assert col in cols, f"{col} missing from gates schema"


def test_default_project_id_empty(tmp_path):
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    store.create_gate(context=_ctx("g2"))
    row = store._con.execute(
        "SELECT project_id FROM gates WHERE gate_ref='g2'"
    ).fetchone()
    assert row[0] == ""
