"""Admin-only cross-tenant session accessor (W32 Track B Gap 4).

This module exposes :func:`admin_get_session`, an unscoped fetch that
bypasses tenant filtering. It is intentionally placed in a private module
(prefix ``_``) so that:

1. The unsafe surface is NOT reachable as an attribute on the public
   ``SessionStore`` class. A tenant-facing handler that mistypes
   ``store.get_unsafe`` will get ``AttributeError`` rather than silently
   leak data across tenants.

2. CI gates restrict imports of this module to an allowlist (admin tooling,
   restart-survival fixtures, cross-tenant audit tests). Adding a new
   importer requires updating the allowlist with a documented reason.

W33 T-16'/T-17' alignment: removes the previously-public
``SessionStore.get_unsafe`` from the tenant-facing class surface. Admin
callers MUST import this function explicitly.

Allowed importers (CI-enforced via scripts/check_admin_session_store_imports.py):
    - hi_agent/server/_admin_session_store.py    (self)
    - tests/integration/**.py                    (test fixtures)
    - tests/server/**.py                         (test fixtures)
    - tests/unit/**.py                           (test fixtures)

Routes, middleware, and tenant-handling code paths are forbidden importers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.server.session_store import SessionRecord, SessionStore


def admin_get_session(store: SessionStore, session_id: str) -> SessionRecord | None:
    """Cross-tenant session fetch — admin tooling only.

    Returns the session record regardless of which tenant owns it. Use
    only from process-internal admin paths that legitimately need to see
    sessions across tenant boundaries (operator drills, restart-survival
    tests, cross-tenant audit harnesses).

    Tenant-facing routes and middleware MUST use
    :meth:`hi_agent.server.session_store.SessionStore.get_for_tenant`
    instead.

    Args:
        store: Initialized ``SessionStore`` instance.
        session_id: Session identifier to fetch.

    Returns:
        ``SessionRecord`` if a row with this ``session_id`` exists in any
        tenant; ``None`` otherwise.
    """
    return store._admin_internal_get(session_id)  # admin shim by design (W32 Track B Gap 4)
