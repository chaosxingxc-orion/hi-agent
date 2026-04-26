"""Unit test: TeamEventStore.insert derives spine fields from exec_ctx."""
import time

from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.server.team_event_store import TeamEvent, TeamEventStore


def _make_store():
    s = TeamEventStore(db_path=":memory:")
    s.initialize()
    return s


def _make_event(event_id="e1", tenant_id="", project_id=""):
    return TeamEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        team_space_id="ts1",
        event_type="test",
        payload_json="{}",
        source_run_id="",
        source_user_id="",
        source_session_id="",
        publish_reason="test",
        schema_version=1,
        created_at=time.time(),
        project_id=project_id,
    )


def test_insert_derives_tenant_id_from_exec_ctx():
    """exec_ctx.tenant_id fills empty event.tenant_id."""
    store = _make_store()
    event = _make_event(event_id="e1", tenant_id="")
    ctx = RunExecutionContext(tenant_id="t-ctx", project_id="p1", run_id="r1")

    store.insert(event, exec_ctx=ctx)

    rows = store.list_since("t-ctx", "ts1")
    assert len(rows) == 1
    assert rows[0].tenant_id == "t-ctx"


def test_insert_derives_project_id_from_exec_ctx():
    """exec_ctx.project_id fills empty event.project_id."""
    store = _make_store()
    event = _make_event(event_id="e2", tenant_id="t1", project_id="")
    ctx = RunExecutionContext(tenant_id="t1", project_id="proj-ctx", run_id="r2")

    store.insert(event, exec_ctx=ctx)

    rows = store.list_since("t1", "ts1")
    assert len(rows) == 1
    assert rows[0].project_id == "proj-ctx"


def test_insert_explicit_tenant_wins_over_exec_ctx():
    """Explicit event.tenant_id is not overwritten by exec_ctx."""
    store = _make_store()
    event = _make_event(event_id="e3", tenant_id="explicit-t")
    ctx = RunExecutionContext(tenant_id="ctx-t", run_id="r3")

    store.insert(event, exec_ctx=ctx)

    rows = store.list_since("explicit-t", "ts1")
    assert len(rows) == 1
    assert rows[0].tenant_id == "explicit-t"


def test_team_event_has_project_id_field():
    """TeamEvent dataclass has project_id field with default ''."""
    e = TeamEvent(
        event_id="x",
        tenant_id="t",
        team_space_id="ts",
        event_type="ev",
        payload_json="{}",
        source_run_id="",
        source_user_id="",
        source_session_id="",
        publish_reason="",
        schema_version=1,
        created_at=0.0,
    )
    assert e.project_id == ""
