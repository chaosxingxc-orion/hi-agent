"""Cross-tenant isolation tests for skills handlers in app.py (W5-G).

Skills use a global registry (no per-tenant isolation implemented yet).
These tests document the EXPECTED behavior when per-tenant skill overlay lands.

All tests are marked xfail until the global skill registry is replaced with a
per-tenant-aware overlay (tracked as TODO W5-G in app.py skill handlers).

Layer 2 — Integration: tests wired to the skills handlers.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(
    reason=(
        "Per-tenant skill overlay not yet implemented. Skills use a global registry "
        "accessible to all tenants. W5-G adds TODO comment; full scoping deferred. "
        "When per-tenant overlay lands, Tenant B must receive empty list or 403/404 "
        "for skills not accessible to that tenant."
    ),
    strict=False,
    expiry_wave="Wave 30",
)
def test_skills_list_is_tenant_scoped():
    """GET /skills/list for Tenant B must not return skills scoped to Tenant A only.

    This test documents the expected behavior post per-tenant overlay.
    Currently the global skill registry returns the same list to all tenants.
    """
    # This test will need a real skill loader with per-tenant scoping to pass.
    # For now it is xfail to document the gap.
    pytest.skip("Per-tenant skill overlay not implemented — see TODO W5-G in app.py")


@pytest.mark.xfail(
    reason=(
        "Per-tenant skill status not yet implemented. handle_skills_status uses "
        "the global skill_evolver accessible to all tenants. "
        "When per-tenant overlay lands, this should filter by requesting tenant."
    ),
    strict=False,
    expiry_wave="Wave 30",
)
def test_skills_status_is_tenant_scoped():
    """GET /skills/status must be tenant-scoped when per-tenant overlay lands.

    Currently returns global stats to all authenticated tenants.
    """
    pytest.skip("Per-tenant skill overlay not implemented — see TODO W5-G in app.py")
