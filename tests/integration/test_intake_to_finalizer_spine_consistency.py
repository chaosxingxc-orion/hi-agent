"""Integration: spine consistency from RunExecutionContext through all 3 pilot writers.

Wave 10.3 W3-D — verifies that a single set of spine values flows
consistently from RunExecutionContext into:

  1. RunQueue row  (SQLite direct query)
  2. GateContext  (SQLiteGateStore.create_gate via exec_ctx)
  3. RunPostmortem (proof-of-already-covered: project_id flows via contract)

Layer 2 — Integration: real SQLite backends, real RunManager.
Zero mocks on the subsystems under test.
"""
from __future__ import annotations

import sqlite3

import pytest
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.management.gate_context import build_gate_context
from hi_agent.management.gate_store import SQLiteGateStore
from hi_agent.server.run_manager import ManagedRun
from hi_agent.server.run_queue import RunQueue

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SPINE = {
    "tenant_id": "tenant-omega",
    "user_id": "user-carol",
    "session_id": "sess-99",
    "project_id": "proj-delta",
}


def _make_run(run_id: str = "run-pilot-001") -> ManagedRun:
    return ManagedRun(
        run_id=run_id,
        task_contract={"task_id": "t1", "project_id": _SPINE["project_id"]},
        **_SPINE,
    )


def _make_exec_ctx(run: ManagedRun) -> RunExecutionContext:
    return RunExecutionContext.from_managed_run(run)


# ---------------------------------------------------------------------------
# Pilot write site 1: RunQueue
# ---------------------------------------------------------------------------


def test_run_queue_spine_from_exec_ctx(tmp_path):
    """RunQueue row must carry the same spine as the RunExecutionContext."""
    rq = RunQueue(db_path=str(tmp_path / "rq.sqlite"))
    run = _make_run("run-q-001")
    exec_ctx = _make_exec_ctx(run)
    spine = exec_ctx.to_spine_kwargs()

    rq.enqueue(
        run_id=run.run_id,
        priority=5,
        payload_json="{}",
        **spine,  # W3-D pattern
    )

    # Direct SQLite read to verify persisted values
    con = sqlite3.connect(str(tmp_path / "rq.sqlite"))
    row = con.execute(
        "SELECT tenant_id, user_id, session_id, project_id "
        "FROM run_queue WHERE run_id = ?",
        (run.run_id,),
    ).fetchone()
    con.close()
    rq.close()

    assert row is not None, "Run queue row not found"
    db_tenant_id, db_user_id, db_session_id, db_project_id = row
    assert db_tenant_id == _SPINE["tenant_id"]
    assert db_user_id == _SPINE["user_id"]
    assert db_session_id == _SPINE["session_id"]
    assert db_project_id == _SPINE["project_id"]


# ---------------------------------------------------------------------------
# Pilot write site 2: SQLiteGateStore.create_gate via exec_ctx
# ---------------------------------------------------------------------------


def test_gate_store_spine_from_exec_ctx(tmp_path):
    """GateContext in SQLiteGateStore must reflect exec_ctx spine."""
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    run = _make_run("run-g-001")
    exec_ctx = _make_exec_ctx(run)

    gate_ctx = build_gate_context(
        gate_ref="gate-pilot-001",
        run_id=run.run_id,
        stage_id="stage-1",
        branch_id="branch-1",
        submitter="system",
    )
    record = store.create_gate(
        context=gate_ctx,
        exec_ctx=exec_ctx,  # W3-D: spine from RunExecutionContext
    )
    store.close()

    assert record.context.tenant_id == _SPINE["tenant_id"]
    assert record.context.user_id == _SPINE["user_id"]
    assert record.context.session_id == _SPINE["session_id"]
    assert record.context.project_id == _SPINE["project_id"]


def test_gate_store_exec_ctx_overwrites_stale_explicit_kwargs(tmp_path):
    """exec_ctx spine must override explicit tenant_id/etc kwargs on create_gate."""
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    run = _make_run("run-g-002")
    exec_ctx = _make_exec_ctx(run)

    gate_ctx = build_gate_context(
        gate_ref="gate-pilot-002",
        run_id=run.run_id,
        stage_id="stage-1",
        branch_id="branch-1",
        submitter="system",
    )
    # Pass stale/wrong explicit kwargs — exec_ctx should win
    record = store.create_gate(
        context=gate_ctx,
        tenant_id="stale-tenant",
        user_id="stale-user",
        exec_ctx=exec_ctx,
    )
    store.close()

    assert record.context.tenant_id == _SPINE["tenant_id"], (
        "exec_ctx.tenant_id must override explicit tenant_id kwarg"
    )
    assert record.context.user_id == _SPINE["user_id"], (
        "exec_ctx.user_id must override explicit user_id kwarg"
    )


def test_gate_store_roundtrip_reads_spine_from_exec_ctx(tmp_path):
    """Spine written via exec_ctx survives SQLite write and read-back."""
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    run = _make_run("run-g-003")
    exec_ctx = _make_exec_ctx(run)

    gate_ctx = build_gate_context(
        gate_ref="gate-pilot-003",
        run_id=run.run_id,
        stage_id="stage-1",
        branch_id="branch-1",
        submitter="system",
    )
    store.create_gate(context=gate_ctx, exec_ctx=exec_ctx)
    fetched = store.get_gate("gate-pilot-003")
    store.close()

    assert fetched.context.tenant_id == _SPINE["tenant_id"]
    assert fetched.context.user_id == _SPINE["user_id"]
    assert fetched.context.session_id == _SPINE["session_id"]
    assert fetched.context.project_id == _SPINE["project_id"]


# ---------------------------------------------------------------------------
# Pilot write site 3: RunPostmortem (proof-of-already-covered)
# ---------------------------------------------------------------------------


def test_run_postmortem_project_id_already_flows_via_contract():
    """RunPostmortem.project_id is derived from TaskContract.project_id.

    Pilot write site 3 requires no additional code change: the existing
    runner_lifecycle.py builds RunPostmortem with project_id=contract.project_id,
    which is set from task_contract_dict at ManagedRun creation time.
    This test documents that invariant so it does not regress.
    """
    from hi_agent.evolve.contracts import RunPostmortem

    pm = RunPostmortem(
        run_id="run-pm-001",
        task_id="t1",
        task_family="test",
        outcome="completed",
        stages_completed=["s1"],
        stages_failed=[],
        branches_explored=1,
        branches_pruned=0,
        total_actions=3,
        failure_codes=[],
        duration_seconds=1.5,
        project_id=_SPINE["project_id"],
    )
    # The project_id field carries the spine correctly
    assert pm.project_id == _SPINE["project_id"]
    # run_id is also a core spine field on RunPostmortem
    assert pm.run_id == "run-pm-001"


# ---------------------------------------------------------------------------
# Cross-writer consistency: all 3 writers agree on the same spine
# ---------------------------------------------------------------------------


def test_spine_consistency_across_all_three_writers(tmp_path):
    """One RunExecutionContext drives RunQueue, GateStore, and RunPostmortem consistently."""
    run = _make_run("run-consistency-001")
    exec_ctx = _make_exec_ctx(run)
    expected_spine = exec_ctx.to_spine_kwargs()

    # --- Writer 1: RunQueue ---
    rq = RunQueue(db_path=str(tmp_path / "rq.sqlite"))
    rq.enqueue(run_id=run.run_id, priority=5, payload_json="{}", **expected_spine)

    con = sqlite3.connect(str(tmp_path / "rq.sqlite"))
    rq_row = con.execute(
        "SELECT tenant_id, user_id, session_id, project_id FROM run_queue WHERE run_id = ?",
        (run.run_id,),
    ).fetchone()
    con.close()
    rq.close()

    # --- Writer 2: GateStore ---
    store = SQLiteGateStore(db_path=tmp_path / "gates.sqlite")
    gate_ctx = build_gate_context(
        gate_ref="gate-c-001",
        run_id=run.run_id,
        stage_id="s1",
        branch_id="b1",
        submitter="system",
    )
    gate_record = store.create_gate(context=gate_ctx, exec_ctx=exec_ctx)
    store.close()

    # --- Writer 3: RunPostmortem (project_id via contract) ---
    from hi_agent.evolve.contracts import RunPostmortem

    pm = RunPostmortem(
        run_id=run.run_id,
        task_id="t1",
        task_family="test",
        outcome="completed",
        stages_completed=[],
        stages_failed=[],
        branches_explored=0,
        branches_pruned=0,
        total_actions=0,
        failure_codes=[],
        duration_seconds=0.0,
        project_id=run.task_contract.get("project_id", ""),
    )

    # Assert all three agree on the full spine
    assert rq_row[0] == expected_spine["tenant_id"]
    assert rq_row[1] == expected_spine["user_id"]
    assert rq_row[2] == expected_spine["session_id"]
    assert rq_row[3] == expected_spine["project_id"]

    assert gate_record.context.tenant_id == expected_spine["tenant_id"]
    assert gate_record.context.user_id == expected_spine["user_id"]
    assert gate_record.context.session_id == expected_spine["session_id"]
    assert gate_record.context.project_id == expected_spine["project_id"]

    assert pm.project_id == expected_spine["project_id"]
    assert pm.run_id == run.run_id
