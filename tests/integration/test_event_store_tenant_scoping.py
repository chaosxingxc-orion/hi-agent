"""HD-2 closure: EventStore.get_events tenant scoping regression test.

Pre-W24, EventStore.get_events accepted no tenant_id parameter; any caller
that bypassed the route-level run-ownership check could read events
across tenant boundaries. W24 J2 added a required tenant_id (kwarg) under
research/prod posture; this test pins the behavior.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from hi_agent.server.event_store import SQLiteEventStore, StoredEvent


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "events.db"
    store = SQLiteEventStore(str(db_path))
    yield store
    store.close()


@pytest.fixture
def two_tenants_with_events(store):
    """Persist 2 events for tenant A and 1 event for tenant B on the same run_id."""
    run_id = "shared-run-id"
    store.append(
        StoredEvent(
            event_id="e1",
            run_id=run_id,
            sequence=0,
            event_type="started",
            payload_json='{"k":1}',
            tenant_id="tenant-A",
        )
    )
    store.append(
        StoredEvent(
            event_id="e2",
            run_id=run_id,
            sequence=1,
            event_type="progress",
            payload_json='{"k":2}',
            tenant_id="tenant-A",
        )
    )
    store.append(
        StoredEvent(
            event_id="e3",
            run_id=run_id,
            sequence=2,
            event_type="started",
            payload_json='{"k":3}',
            tenant_id="tenant-B",
        )
    )
    return run_id


class TestGetEventsTenantScoping:
    def test_tenant_a_sees_only_a_events(self, store, two_tenants_with_events):
        run_id = two_tenants_with_events
        events = store.get_events(run_id, tenant_id="tenant-A")
        assert len(events) == 2
        assert all(e["tenant_id"] == "tenant-A" for e in events)
        assert {e["event_id"] for e in events} == {"e1", "e2"}

    def test_tenant_b_sees_only_b_events(self, store, two_tenants_with_events):
        run_id = two_tenants_with_events
        events = store.get_events(run_id, tenant_id="tenant-B")
        assert len(events) == 1
        assert events[0]["tenant_id"] == "tenant-B"
        assert events[0]["event_id"] == "e3"

    def test_unknown_tenant_sees_zero_events(self, store, two_tenants_with_events):
        run_id = two_tenants_with_events
        events = store.get_events(run_id, tenant_id="tenant-not-real")
        assert events == []

    def test_missing_tenant_id_raises_under_research_posture(
        self, store, two_tenants_with_events, monkeypatch
    ):
        run_id = two_tenants_with_events
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        with pytest.raises(ValueError, match="requires tenant_id"):
            store.get_events(run_id)

    def test_missing_tenant_id_raises_under_prod_posture(
        self, store, two_tenants_with_events, monkeypatch
    ):
        run_id = two_tenants_with_events
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        with pytest.raises(ValueError, match="requires tenant_id"):
            store.get_events(run_id)

    def test_missing_tenant_id_returns_all_under_dev_posture(
        self, store, two_tenants_with_events, monkeypatch
    ):
        run_id = two_tenants_with_events
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        events = store.get_events(run_id)
        assert len(events) == 3

    def test_get_events_unsafe_returns_all_regardless_of_posture(
        self, store, two_tenants_with_events, monkeypatch
    ):
        run_id = two_tenants_with_events
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        events = store.get_events_unsafe(run_id)
        assert len(events) == 3
