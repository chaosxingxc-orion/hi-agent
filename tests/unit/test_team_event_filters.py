"""Tests for G-6: TeamEventStore list() supports event_type/source_run_id/order/limit filters."""
import uuid

import pytest


@pytest.fixture
def store(tmp_path):
    from hi_agent.server.team_event_store import TeamEventStore
    s = TeamEventStore(db_path=str(tmp_path / "team.db"))
    s.initialize()
    return s


def _append(store, tenant, space, event_type, source_run_id="", data=None):
    import time

    from hi_agent.server.team_event_store import TeamEvent
    event = TeamEvent(
        event_id=str(uuid.uuid4()),
        tenant_id=tenant,
        team_space_id=space,
        event_type=event_type,
        payload_json="{}",
        source_run_id=source_run_id,
        source_user_id="",
        source_session_id="",
        publish_reason="",
        schema_version=1,
        created_at=time.time(),
    )
    store.insert(event)


def test_filter_by_event_type(store):
    _append(store, "t1", "s1", "paper.ingested")
    _append(store, "t1", "s1", "opinion.v1")
    _append(store, "t1", "s1", "paper.ingested")
    results = store.list(tenant_id="t1", team_space_id="s1", event_types=["paper.ingested"])
    assert len(results) == 2
    assert all(r.event_type == "paper.ingested" for r in results)


def test_filter_by_source_run_id(store):
    _append(store, "t1", "s1", "experiment.result_posted", source_run_id="run-A")
    _append(store, "t1", "s1", "experiment.result_posted", source_run_id="run-B")
    results = store.list(tenant_id="t1", team_space_id="s1", source_run_ids=["run-A"])
    assert len(results) == 1
    assert results[0].source_run_id == "run-A"


def test_descending_order(store):
    for i in range(3):
        _append(store, "t1", "s1", f"event-{i}")
    asc = store.list(tenant_id="t1", team_space_id="s1", order="asc")
    desc = store.list(tenant_id="t1", team_space_id="s1", order="desc")
    assert [r.event_type for r in asc] == list(reversed([r.event_type for r in desc]))


def test_limit(store):
    for _ in range(10):
        _append(store, "t1", "s1", "fact")
    results = store.list(tenant_id="t1", team_space_id="s1", limit=3)
    assert len(results) == 3


def test_no_filters_returns_all(store):
    for i in range(5):
        _append(store, "t1", "s1", f"ev-{i}")
    results = store.list(tenant_id="t1", team_space_id="s1")
    assert len(results) == 5


def test_since_id_still_works(store):
    _append(store, "t1", "s1", "ev-1")
    _append(store, "t1", "s1", "ev-2")
    # list_since should still work
    all_events = store.list_since("t1", "s1", since_id=0)
    assert len(all_events) == 2
    # list() with since_id
    partial = store.list(tenant_id="t1", team_space_id="s1", since_id=1)
    assert len(partial) == 1


def test_multiple_event_types(store):
    _append(store, "t1", "s1", "type-A")
    _append(store, "t1", "s1", "type-B")
    _append(store, "t1", "s1", "type-C")
    results = store.list(tenant_id="t1", team_space_id="s1", event_types=["type-A", "type-C"])
    assert len(results) == 2
    types = {r.event_type for r in results}
    assert types == {"type-A", "type-C"}
