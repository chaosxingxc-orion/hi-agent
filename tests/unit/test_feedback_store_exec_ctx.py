"""Unit test: FeedbackStore.submit derives spine fields from exec_ctx."""
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.evolve.feedback_store import FeedbackStore, RunFeedback


def _make_store():
    return FeedbackStore(storage_path=None)


def _make_feedback(run_id="r1", tenant_id="", user_id="", session_id="", project_id=""):
    return RunFeedback(
        run_id=run_id,
        rating=0.8,
        notes="test",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
    )


def test_submit_derives_tenant_id_from_exec_ctx():
    """exec_ctx.tenant_id fills empty feedback.tenant_id."""
    store = _make_store()
    fb = _make_feedback(run_id="r1", tenant_id="")
    ctx = RunExecutionContext(tenant_id="t-ctx", user_id="u1", run_id="r1")

    store.submit(fb, exec_ctx=ctx)

    retrieved = store.get("r1")
    assert retrieved is not None
    assert retrieved.tenant_id == "t-ctx"


def test_submit_derives_user_id_from_exec_ctx():
    """exec_ctx.user_id fills empty feedback.user_id."""
    store = _make_store()
    fb = _make_feedback(run_id="r2", tenant_id="t1", user_id="")
    ctx = RunExecutionContext(tenant_id="t1", user_id="u-ctx", run_id="r2")

    store.submit(fb, exec_ctx=ctx)

    retrieved = store.get("r2")
    assert retrieved is not None
    assert retrieved.user_id == "u-ctx"


def test_submit_derives_project_id_from_exec_ctx():
    """exec_ctx.project_id fills empty feedback.project_id."""
    store = _make_store()
    fb = _make_feedback(run_id="r3", tenant_id="t1", project_id="")
    ctx = RunExecutionContext(tenant_id="t1", project_id="proj-ctx", run_id="r3")

    store.submit(fb, exec_ctx=ctx)

    retrieved = store.get("r3")
    assert retrieved is not None
    assert retrieved.project_id == "proj-ctx"


def test_submit_explicit_fields_win_over_exec_ctx():
    """Explicit feedback fields are not overwritten by exec_ctx."""
    store = _make_store()
    fb = _make_feedback(run_id="r4", tenant_id="explicit-t", user_id="explicit-u")
    ctx = RunExecutionContext(tenant_id="ctx-t", user_id="ctx-u", run_id="r4")

    store.submit(fb, exec_ctx=ctx)

    retrieved = store.get("r4")
    assert retrieved is not None
    assert retrieved.tenant_id == "explicit-t"
    assert retrieved.user_id == "explicit-u"
