import time

import pytest
from hi_agent.server.event_store import SQLiteEventStore, StoredEvent
from hi_agent.server.run_store import RunRecord, SQLiteRunStore


@pytest.fixture
def run_store(tmp_path):
    s = SQLiteRunStore(str(tmp_path / "runs.db"))
    return s


@pytest.fixture
def event_store(tmp_path):
    s = SQLiteEventStore(str(tmp_path / "events.db"))
    return s


def test_run_record_has_user_and_session(run_store):
    record = RunRecord(
        run_id="r1",
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        task_contract_json="{}",
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=time.time(),
        updated_at=time.time(),
    )
    run_store.upsert(record)
    found = run_store.get_by_workspace(run_id="r1", tenant_id="t1", user_id="u1", session_id="s1")
    assert found is not None
    assert found.user_id == "u1"


def test_run_store_workspace_filter_excludes_other_user(run_store):
    record = RunRecord(
        run_id="r2",
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        task_contract_json="{}",
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=time.time(),
        updated_at=time.time(),
    )
    run_store.upsert(record)
    assert run_store.get_by_workspace("r2", "t1", "u2", "s1") is None


def test_event_store_has_workspace_columns(event_store):
    evt = StoredEvent(
        event_id="e1",
        run_id="r1",
        sequence=1,
        event_type="test",
        payload_json="{}",
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
    )
    event_store.append(evt)
    events = event_store.list_since(
        run_id="r1", last_id=0, tenant_id="t1", user_id="u1", session_id="s1"
    )
    assert len(events) == 1
    assert events[0].user_id == "u1"
