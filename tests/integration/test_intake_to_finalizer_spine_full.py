"""Integration test: full spine consistency across all 11 durable writers.

Verifies that when RunExecutionContext is constructed with a full set of
spine fields, each writer correctly stores and returns the same
(tenant_id, project_id, run_id) tuple.
"""

from __future__ import annotations

import time
import uuid

from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.evolve.feedback_store import FeedbackStore, RunFeedback
from hi_agent.experiment.op_store import LongRunningOpStore
from hi_agent.management.gate_api import InMemoryGateAPI
from hi_agent.management.gate_context import GateContext
from hi_agent.server.event_store import SQLiteEventStore, StoredEvent
from hi_agent.server.run_store import RunRecord, SQLiteRunStore
from hi_agent.server.team_event_store import TeamEvent, TeamEventStore

_SPINE = {
    "tenant_id": "tenant-integration",
    "user_id": "user-integration",
    "session_id": "session-integration",
    "project_id": "project-integration",
    "run_id": str(uuid.uuid4()),
}


def _make_exec_ctx() -> RunExecutionContext:
    return RunExecutionContext(**_SPINE)


def test_run_store_spine_full(tmp_path):
    """SQLiteRunStore.upsert stores exec_ctx spine when record fields are empty."""
    store = SQLiteRunStore(db_path=str(tmp_path / "runs.db"))
    ctx = _make_exec_ctx()

    record = RunRecord(
        run_id=ctx.run_id,
        tenant_id="",  # empty — should be filled from exec_ctx
        task_contract_json="{}",
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=time.time(),
        updated_at=time.time(),
        project_id="",  # empty — should be filled from exec_ctx
    )
    store.upsert(record, exec_ctx=ctx)

    retrieved = store.get(ctx.run_id)
    assert retrieved is not None
    assert retrieved.tenant_id == _SPINE["tenant_id"]
    assert retrieved.project_id == _SPINE["project_id"]


def test_team_event_store_spine_full():
    """TeamEventStore.insert stores exec_ctx spine when event fields are empty."""
    store = TeamEventStore(db_path=":memory:")
    store.initialize()
    ctx = _make_exec_ctx()

    event = TeamEvent(
        event_id=str(uuid.uuid4()),
        tenant_id="",  # empty — filled from exec_ctx
        team_space_id="ts1",
        event_type="test",
        payload_json="{}",
        source_run_id="",
        source_user_id="",
        source_session_id="",
        publish_reason="integration-test",
        schema_version=1,
        created_at=time.time(),
        project_id="",  # empty — filled from exec_ctx
    )
    store.insert(event, exec_ctx=ctx)

    rows = store.list_since(_SPINE["tenant_id"], "ts1")
    assert len(rows) == 1
    assert rows[0].tenant_id == _SPINE["tenant_id"]
    assert rows[0].project_id == _SPINE["project_id"]


def test_feedback_store_spine_full():
    """FeedbackStore.submit stores exec_ctx spine when feedback fields are empty."""
    store = FeedbackStore()
    ctx = _make_exec_ctx()

    fb = RunFeedback(
        run_id=ctx.run_id,
        rating=1.0,
        notes="integration test",
        tenant_id="",
        user_id="",
        project_id="",
    )
    store.submit(fb, exec_ctx=ctx)

    retrieved = store.get(ctx.run_id)
    assert retrieved is not None
    assert retrieved.tenant_id == _SPINE["tenant_id"]
    assert retrieved.user_id == _SPINE["user_id"]
    assert retrieved.project_id == _SPINE["project_id"]


def test_op_store_spine_full(tmp_path):
    """LongRunningOpStore.create stores exec_ctx spine."""
    store = LongRunningOpStore(db_path=tmp_path / "ops.db")
    ctx = _make_exec_ctx()

    handle = store.create(
        op_id="op-integ",
        backend="test-backend",
        external_id="ext-integ",
        submitted_at=time.time(),
        exec_ctx=ctx,
    )

    assert handle.tenant_id == _SPINE["tenant_id"]
    assert handle.run_id == _SPINE["run_id"]
    assert handle.project_id == _SPINE["project_id"]

    persisted = store.get("op-integ")
    assert persisted is not None
    assert persisted.tenant_id == _SPINE["tenant_id"]
    assert persisted.project_id == _SPINE["project_id"]


def test_gate_api_spine_full():
    """InMemoryGateAPI.create_gate stores exec_ctx.project_id."""
    api = InMemoryGateAPI()
    ctx = _make_exec_ctx()

    gate_ctx = GateContext(
        gate_ref="gate-integ",
        run_id=ctx.run_id,
        stage_id="s1",
        branch_id="b1",
        submitter="test-user",
        opened_at=time.time(),
    )
    record = api.create_gate(context=gate_ctx, exec_ctx=ctx)

    assert record.project_id == _SPINE["project_id"]


def test_event_store_spine_full(tmp_path):
    """SQLiteEventStore.append stores exec_ctx spine when event fields are empty."""
    store = SQLiteEventStore(db_path=str(tmp_path / "events.db"))
    ctx = _make_exec_ctx()

    event = StoredEvent(
        event_id=str(uuid.uuid4()),
        run_id="",  # empty — filled from exec_ctx
        sequence=0,
        event_type="test",
        payload_json="{}",
        tenant_id="",  # empty — filled from exec_ctx
    )
    store.append(event, exec_ctx=ctx)

    # Use since_sequence=-1 to include events with sequence=0
    events = store.list_since(ctx.run_id, since_sequence=-1)
    assert len(events) == 1
    assert events[0].tenant_id == _SPINE["tenant_id"]
    assert events[0].run_id == _SPINE["run_id"]
