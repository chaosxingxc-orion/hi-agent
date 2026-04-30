"""Integration: SessionStore persists sessions across restarts.

Verifies that session data written by one store instance is readable from a
fresh instance pointing at the same SQLite file, confirming restart-survival
of the WAL-backed SQLite store (Rule 2 RO track: durable-store changes require
restart-survival test).
"""

from __future__ import annotations

import pytest
from hi_agent.server.session_store import SessionStore


@pytest.mark.serial
def test_session_survives_restart(tmp_path):
    """Session created in store1 is readable from store2 (restart simulation)."""
    db = tmp_path / "sessions.db"

    store1 = SessionStore(db_path=db)
    store1.initialize()
    sid = store1.create(tenant_id="t-test", user_id="u-1", name="my-session")
    # Simulate process death by closing the underlying connection.
    store1._conn.close()

    store2 = SessionStore(db_path=db)
    store2.initialize()
    record = store2.get_unsafe(sid)
    assert record is not None, "Session not found after restart"
    assert record.tenant_id == "t-test"
    assert record.user_id == "u-1"
    assert record.name == "my-session"
    assert record.status == "active"


@pytest.mark.serial
def test_session_tenant_scoped_read_survives_restart(tmp_path):
    """get_for_tenant returns the session from a freshly opened store."""
    db = tmp_path / "sessions_tenant.db"

    store1 = SessionStore(db_path=db)
    store1.initialize()
    sid = store1.create(tenant_id="t-alpha", user_id="u-2")
    store1._conn.close()

    store2 = SessionStore(db_path=db)
    store2.initialize()
    record = store2.get_for_tenant(sid, tenant_id="t-alpha")
    assert record is not None, "Tenant-scoped session not found after restart"
    assert record.session_id == sid
    assert record.tenant_id == "t-alpha"

    # Cross-tenant isolation must hold across restart.
    other = store2.get_for_tenant(sid, tenant_id="t-other")
    assert other is None, "Cross-tenant isolation violated after restart"


@pytest.mark.serial
def test_archived_session_persists_across_restart(tmp_path):
    """Archiving a session in store1 is durable and visible in store2."""
    db = tmp_path / "sessions_archive.db"

    store1 = SessionStore(db_path=db)
    store1.initialize()
    sid = store1.create(tenant_id="t-beta", user_id="u-3")
    store1.archive(sid, tenant_id="t-beta", user_id="u-3")
    store1._conn.close()

    store2 = SessionStore(db_path=db)
    store2.initialize()
    record = store2.get_unsafe(sid)
    assert record is not None
    assert record.status == "archived"
    assert record.archived_at is not None
