"""Tests for RunManager workspace enforcement.

Verifies that tenant_id/user_id/session_id fields are bound to ManagedRun,
and that get_run/list_runs/cancel_run scope to workspace correctly.
"""

import uuid

import pytest
from hi_agent.server.run_manager import RunManager
from hi_agent.server.tenant_context import TenantContext


def make_ctx(user_id: str = "u1", session_id: str = "s1", tenant_id: str = "t1") -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id)


@pytest.fixture
def manager():
    return RunManager(max_concurrent=1, queue_size=4)


def test_create_run_binds_workspace(manager):
    ctx = make_ctx()
    run_id = manager.create_run({"goal": "test"}, workspace=ctx).run_id
    run = manager.get_run(run_id, workspace=ctx)
    assert run is not None
    assert run.user_id == "u1"
    assert run.session_id == "s1"


def test_get_run_wrong_user_returns_none(manager):
    ctx1 = make_ctx(user_id="u1")
    ctx2 = make_ctx(user_id="u2")
    run_id = manager.create_run({"goal": "test"}, workspace=ctx1).run_id
    assert manager.get_run(run_id, workspace=ctx2) is None


def test_list_runs_filters_by_workspace(manager):
    ctx1 = make_ctx(user_id="u1", session_id="s1")
    ctx2 = make_ctx(user_id="u2", session_id="s2")
    manager.create_run({"goal": "a"}, workspace=ctx1)
    manager.create_run({"goal": "b"}, workspace=ctx2)
    runs = manager.list_runs(workspace=ctx1)
    assert all(r.user_id == "u1" for r in runs)
    assert len(runs) == 1


def test_cancel_run_wrong_user_returns_false(manager):
    ctx1 = make_ctx(user_id="u1")
    ctx2 = make_ctx(user_id="u2")
    run_id = manager.create_run({"goal": "test"}, workspace=ctx1).run_id
    result = manager.cancel_run(run_id, workspace=ctx2)
    assert result is False


def test_duplicate_task_id_raises(manager):
    ctx = make_ctx()
    manager.create_run({"goal": "first", "task_id": "dup"}, workspace=ctx)
    with pytest.raises(ValueError, match="already exists"):
        manager.create_run({"goal": "second", "task_id": "dup"}, workspace=ctx)


def test_run_id_is_uuid4(manager):
    ctx = make_ctx()
    run_id = manager.create_run({"goal": "test"}, workspace=ctx).run_id
    parsed = uuid.UUID(run_id, version=4)
    assert str(parsed) == run_id
