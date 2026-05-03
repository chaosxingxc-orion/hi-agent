"""Tests for SessionStore — SQLite-backed session CRUD."""

import pytest
from hi_agent.server._admin_session_store import admin_get_session
from hi_agent.server.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    s = SessionStore(str(tmp_path / "sessions.db"))
    s.initialize()
    return s


def test_create_and_get(store):
    sid = store.create(tenant_id="t1", user_id="u1", team_id="eng")
    rec = admin_get_session(store, sid)
    assert rec is not None
    assert rec.session_id == sid
    assert rec.tenant_id == "t1"
    assert rec.user_id == "u1"
    assert rec.status == "active"


def test_get_nonexistent_returns_none(store):
    assert admin_get_session(store, "does-not-exist") is None


def test_validate_ownership_true(store):
    sid = store.create(tenant_id="t1", user_id="u1")
    assert store.validate_ownership(sid, tenant_id="t1", user_id="u1") is True


def test_validate_ownership_wrong_user(store):
    sid = store.create(tenant_id="t1", user_id="u1")
    assert store.validate_ownership(sid, tenant_id="t1", user_id="u2") is False


def test_list_active(store):
    s1 = store.create(tenant_id="t1", user_id="u1")
    s2 = store.create(tenant_id="t1", user_id="u1")
    store.archive(s1, tenant_id="t1", user_id="u1")
    active = store.list_active(tenant_id="t1", user_id="u1")
    ids = [r.session_id for r in active]
    assert s2 in ids
    assert s1 not in ids


def test_archive(store):
    sid = store.create(tenant_id="t1", user_id="u1")
    store.archive(sid, tenant_id="t1", user_id="u1")
    rec = admin_get_session(store, sid)
    assert rec.status == "archived"


def test_archive_wrong_user_raises(store):
    sid = store.create(tenant_id="t1", user_id="u1")
    with pytest.raises(PermissionError):
        store.archive(sid, tenant_id="t1", user_id="u2")


def test_validate_ownership_archived_session_returns_false(store):
    sid = store.create(tenant_id="t1", user_id="u1")
    store.archive(sid, tenant_id="t1", user_id="u1")
    assert store.validate_ownership(sid, "t1", "u1") is False
