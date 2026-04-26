"""Unit test: InMemoryGateAPI.create_gate propagates spine from exec_ctx."""
import time

from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.management.gate_api import InMemoryGateAPI
from hi_agent.management.gate_context import GateContext


def _make_context(gate_ref="g1", run_id="r1"):
    return GateContext(
        gate_ref=gate_ref,
        run_id=run_id,
        stage_id="s1",
        branch_id="b1",
        submitter="user1",
        opened_at=time.time(),
    )


def test_create_gate_derives_project_id_from_exec_ctx():
    """exec_ctx.project_id is stored as GateRecord.project_id."""
    api = InMemoryGateAPI()
    ctx = RunExecutionContext(tenant_id="t1", project_id="proj-ctx", run_id="r1")
    context = _make_context(gate_ref="g1", run_id="r1")

    record = api.create_gate(context=context, exec_ctx=ctx)

    assert record.project_id == "proj-ctx"


def test_create_gate_without_exec_ctx_has_empty_project_id():
    """Without exec_ctx, project_id defaults to empty string."""
    api = InMemoryGateAPI()
    context = _make_context(gate_ref="g2", run_id="r2")

    record = api.create_gate(context=context)

    assert record.project_id == ""


def test_create_gate_with_none_exec_ctx():
    """exec_ctx=None behaves like omitting exec_ctx."""
    api = InMemoryGateAPI()
    context = _make_context(gate_ref="g3", run_id="r3")

    record = api.create_gate(context=context, exec_ctx=None)

    assert record.project_id == ""


def test_create_gate_spine_propagated_in_record():
    """GateRecord reflects exec_ctx spine for downstream queries."""
    api = InMemoryGateAPI()
    ctx = RunExecutionContext(
        tenant_id="t1",
        user_id="u1",
        project_id="proj1",
        run_id="r4",
    )
    context = _make_context(gate_ref="g4", run_id="r4")

    api.create_gate(context=context, exec_ctx=ctx)
    fetched = api.get_gate("g4")

    assert fetched.project_id == "proj1"
