"""Unit test: LongRunningOpStore.create uses exec_ctx spine fields."""
import time

from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.experiment.op_store import LongRunningOpStore


def _make_store(tmp_path):
    return LongRunningOpStore(db_path=tmp_path / "ops.db")


def test_create_derives_tenant_from_exec_ctx(tmp_path):
    """exec_ctx.tenant_id overrides empty tenant_id kwarg."""
    store = _make_store(tmp_path)
    ctx = RunExecutionContext(tenant_id="t-ctx", run_id="r1", project_id="p1")

    handle = store.create(
        op_id="op1",
        backend="b",
        external_id="ext1",
        submitted_at=time.time(),
        exec_ctx=ctx,
    )

    assert handle.tenant_id == "t-ctx"
    assert handle.run_id == "r1"
    assert handle.project_id == "p1"


def test_create_exec_ctx_wins_over_kwargs_for_spine(tmp_path):
    """exec_ctx spine fields override explicit kwargs for tenant/run/project."""
    store = _make_store(tmp_path)
    ctx = RunExecutionContext(tenant_id="ctx-t", run_id="ctx-r", project_id="ctx-p")

    handle = store.create(
        op_id="op2",
        backend="b",
        external_id="ext2",
        submitted_at=time.time(),
        tenant_id="kwarg-t",
        run_id="kwarg-r",
        project_id="kwarg-p",
        exec_ctx=ctx,
    )

    assert handle.tenant_id == "ctx-t"
    assert handle.run_id == "ctx-r"
    assert handle.project_id == "ctx-p"


def test_create_without_exec_ctx_uses_kwargs(tmp_path):
    """Without exec_ctx, explicit kwargs are used directly."""
    store = _make_store(tmp_path)

    handle = store.create(
        op_id="op3",
        backend="b",
        external_id="ext3",
        submitted_at=time.time(),
        tenant_id="kwarg-t",
        run_id="kwarg-r",
    )

    assert handle.tenant_id == "kwarg-t"
    assert handle.run_id == "kwarg-r"


def test_create_persists_spine_fields(tmp_path):
    """Spine fields from exec_ctx are stored and retrievable via get()."""
    store = _make_store(tmp_path)
    ctx = RunExecutionContext(tenant_id="t1", run_id="r1", project_id="p1")

    store.create(
        op_id="op4",
        backend="b",
        external_id="ext4",
        submitted_at=time.time(),
        exec_ctx=ctx,
    )

    retrieved = store.get("op4")
    assert retrieved is not None
    assert retrieved.tenant_id == "t1"
    assert retrieved.run_id == "r1"
    assert retrieved.project_id == "p1"
