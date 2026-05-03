"""Integration tests for SessionStore tenant scoping (HD-3 / W24-J3).

Layer 2 — Integration: real SQLite SessionStore (no mocks).

Verifies that ``get_for_tenant`` filters by tenant_id and that
``admin_get_session`` (W32 Track B Gap 4 — moved out of the public class
into ``hi_agent.server._admin_session_store``) is the admin-only escape
hatch.

HD-3 root cause:
    SessionStore.get(session_id) returned a record regardless of which
    tenant owned it, allowing a tenant-scoped HTTP handler to retrieve
    another tenant's session by id (existence-leak / cross-tenant access).
"""

from __future__ import annotations

import pytest
from hi_agent.server._admin_session_store import admin_get_session
from hi_agent.server.session_store import SessionStore


@pytest.fixture()
def store(tmp_path):
    """Real SQLite-backed SessionStore (no mocks)."""
    s = SessionStore(db_path=str(tmp_path / "sessions.db"))
    s.initialize()
    yield s


class TestGetForTenantScoping:
    """``get_for_tenant`` MUST filter by tenant_id."""

    def test_same_tenant_returns_record(self, store):
        """Lookup with the owning tenant returns the SessionRecord."""
        sid = store.create(tenant_id="tenant-A", user_id="user-1")

        rec = store.get_for_tenant(sid, "tenant-A")

        assert rec is not None
        assert rec.session_id == sid
        assert rec.tenant_id == "tenant-A"
        assert rec.user_id == "user-1"

    def test_cross_tenant_returns_none(self, store):
        """Lookup with a different tenant id returns None — no record leakage."""
        sid = store.create(tenant_id="tenant-A", user_id="user-1")

        # Tenant B asks for tenant A's session by id.
        rec = store.get_for_tenant(sid, "tenant-B")

        assert rec is None

    def test_cross_tenant_indistinguishable_from_missing(self, store):
        """A session belonging to another tenant looks identical to a missing
        session.

        Both return ``None`` so that the caller cannot infer that the id
        exists in another tenant.
        """
        sid = store.create(tenant_id="tenant-A", user_id="user-1")

        cross_tenant = store.get_for_tenant(sid, "tenant-B")
        truly_missing = store.get_for_tenant("does-not-exist", "tenant-B")

        # Both branches return the same outcome.
        assert cross_tenant is None
        assert truly_missing is None

    def test_nonexistent_session_returns_none(self, store):
        """Unknown session ids return None for any tenant."""
        assert store.get_for_tenant("no-such-id", "tenant-A") is None

    def test_archived_session_still_returned_for_owning_tenant(self, store):
        """``get_for_tenant`` does not implicitly filter by status; archived
        sessions are returned to the owning tenant (status filtering is the
        caller's responsibility, e.g. via list_active or validate_ownership).
        """
        sid = store.create(tenant_id="tenant-A", user_id="user-1")
        store.archive(sid, tenant_id="tenant-A", user_id="user-1")

        rec = store.get_for_tenant(sid, "tenant-A")

        assert rec is not None
        assert rec.status == "archived"


class TestAdminGetSession:
    """``admin_get_session`` (private module) is the admin-only escape hatch."""

    def test_admin_get_session_returns_record_for_owning_tenant(self, store):
        sid = store.create(tenant_id="tenant-A", user_id="user-1")
        rec = admin_get_session(store, sid)
        assert rec is not None
        assert rec.tenant_id == "tenant-A"

    def test_admin_get_session_returns_record_regardless_of_tenant(self, store):
        """``admin_get_session`` MUST NOT filter by tenant — that is the whole point.

        Admin tooling needs to retrieve sessions across tenants. The safety
        promise is that ``admin_get_session`` is gated by an import-allowlist
        and never appears on a tenant-scoped public path; this test protects
        the unscoped contract.
        """
        sid = store.create(tenant_id="tenant-A", user_id="user-1")

        # Caller passes no tenant; record is returned anyway.
        rec = admin_get_session(store, sid)

        assert rec is not None
        assert rec.session_id == sid
        assert rec.tenant_id == "tenant-A"

    def test_admin_get_session_missing_returns_none(self, store):
        assert admin_get_session(store, "nope") is None

    def test_public_class_does_not_expose_get_unsafe(self):
        """W32 Track B Gap 4: SessionStore must NOT expose ``get_unsafe``.

        The unsafe accessor was moved into a private module
        (``hi_agent.server._admin_session_store``) so route handlers and
        middleware that mistype the method name get an AttributeError
        rather than a silent cross-tenant data leak.
        """
        assert not hasattr(SessionStore, "get_unsafe"), (
            "SessionStore.get_unsafe must NOT exist on the public class. "
            "Use hi_agent.server._admin_session_store.admin_get_session "
            "instead."
        )
