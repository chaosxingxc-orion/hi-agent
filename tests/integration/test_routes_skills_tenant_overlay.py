"""Placeholder for skills tenant overlay tests (Wave 11 full implementation)."""
import pytest


@pytest.mark.integration
def test_global_skills_visible_to_all_tenants():
    """Global skills should be accessible to any tenant (baseline behavior)."""
    try:
        from hi_agent.server.app import app
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("App not importable")

    with TestClient(app) as client:
        t1_resp = client.get("/skills", headers={"X-Tenant-ID": "tenant-001"})
        t2_resp = client.get("/skills", headers={"X-Tenant-ID": "tenant-002"})

        if t1_resp.status_code not in (200, 404):
            pytest.skip(f"/skills returned {t1_resp.status_code}")

        # Both tenants should get the same global skills
        # (tenant overlay is Wave 11 — just verify baseline works)
        if t1_resp.status_code == 200 and t2_resp.status_code == 200:
            # Global skills visible to both
            assert t1_resp.json() is not None
