import time

import pytest
from hi_agent.server.team_event_store import TeamEvent, TeamEventStore


@pytest.fixture
def store(tmp_path):
    s = TeamEventStore(str(tmp_path / "team.db"))
    s.initialize()
    return s


def test_insert_and_list(store):
    evt = TeamEvent(
        event_id="e1", tenant_id="t1", team_space_id="team-eng",
        event_type="insight", payload_json='{"key": "val"}',
        source_run_id="run-1", source_user_id="u1", source_session_id="s1",
        publish_reason="explicit", schema_version=1, created_at=time.time(),
    )
    store.insert(evt)
    events = store.list_since(tenant_id="t1", team_space_id="team-eng", since_id=0)
    assert len(events) == 1
    assert events[0].event_type == "insight"


def test_list_wrong_team_returns_empty(store):
    evt = TeamEvent(
        event_id="e2", tenant_id="t1", team_space_id="team-eng",
        event_type="decision", payload_json="{}",
        source_run_id="r1", source_user_id="u1", source_session_id="s1",
        publish_reason="explicit", schema_version=1, created_at=time.time(),
    )
    store.insert(evt)
    assert store.list_since("t1", "other-team", since_id=0) == []


def test_provenance_fields_stored(store):
    evt = TeamEvent(
        event_id="e3", tenant_id="t1", team_space_id="t1",
        event_type="artifact", payload_json="{}",
        source_run_id="run-x", source_user_id="alice", source_session_id="ses-99",
        publish_reason="auto_sync", schema_version=1, created_at=time.time(),
    )
    store.insert(evt)
    result = store.list_since("t1", "t1", since_id=0)[0]
    assert result.source_user_id == "alice"
    assert result.publish_reason == "auto_sync"


def test_concurrent_inserts_all_persisted(store):
    import threading
    errors = []
    def insert_one(i):
        try:
            store.insert(TeamEvent(
                event_id=f"e{i}", tenant_id="t1", team_space_id="t1",
                event_type="test", payload_json="{}", source_run_id=f"r{i}",
                source_user_id="u1", source_session_id="s1",
                publish_reason="test", schema_version=1, created_at=time.time(),
            ))
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=insert_one, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(store.list_since("t1", "t1", since_id=0)) == 10
