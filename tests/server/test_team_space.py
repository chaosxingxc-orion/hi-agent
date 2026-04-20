import pytest
from hi_agent.server.team_event_store import TeamEventStore
from hi_agent.server.team_space import TeamSpace


@pytest.fixture
def store(tmp_path):
    s = TeamEventStore(str(tmp_path / "team.db"))
    s.initialize()
    return s


def test_publish_persists_event(store):
    ts = TeamSpace(tenant_id="t1", team_space_id="eng", event_store=store)
    ts.publish(
        event_type="insight",
        payload={"finding": "users prefer X"},
        source_run_id="run-1",
        source_user_id="u1",
        source_session_id="s1",
        publish_reason="explicit",
    )
    events = store.list_since("t1", "eng", since_id=0)
    assert len(events) == 1
    assert events[0].event_type == "insight"
    assert events[0].source_user_id == "u1"


def test_publish_schema_version_defaults_to_1(store):
    ts = TeamSpace(tenant_id="t1", team_space_id="eng", event_store=store)
    ts.publish(
        event_type="decision",
        payload={},
        source_run_id="r1",
        source_user_id="u1",
        source_session_id="s1",
        publish_reason="explicit",
    )
    events = store.list_since("t1", "eng", since_id=0)
    assert events[0].schema_version == 1


def test_publish_payload_round_trips(store):
    ts = TeamSpace(tenant_id="t1", team_space_id="eng", event_store=store)
    ts.publish(
        event_type="artifact",
        payload={"key": "value", "n": 42},
        source_run_id="r1",
        source_user_id="u1",
        source_session_id="s1",
        publish_reason="explicit",
    )
    events = store.list_since("t1", "eng", since_id=0)
    import json

    payload = json.loads(events[0].payload_json)
    assert payload == {"key": "value", "n": 42}
