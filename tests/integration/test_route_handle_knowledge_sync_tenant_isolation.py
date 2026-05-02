"""Tenant isolation: KG sync read-path tenant-scoped (W31 T-4').

Pre-W31: ``export_visualization`` (used by the sync route) selected
``profile_id+project_id`` rows but ignored ``tenant_id`` in the WHERE clause,
so a tenant calling sync re-rendered all tenants' nodes that shared its
profile.  W31 T-4' adds the tenant_id filter.

Layer 2 — Integration: real ``SqliteKnowledgeGraphBackend`` instances; no
mocks on the subsystem under test.
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


class TestKnowledgeSyncTenantIsolation:
    """Sync-path reads are scoped to the calling tenant (W31 T-4')."""

    def test_export_visualization_returns_only_calling_tenant_nodes(self, tmp_path):
        """The exported visualization contains only the calling tenant's rows."""
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        kg_a = SqliteKnowledgeGraphBackend(
            data_dir=tmp_path / "shared",
            profile_id="shared_profile",
            tenant_id="isolation-tenant-A",
        )
        kg_b = SqliteKnowledgeGraphBackend(
            data_dir=tmp_path / "shared",
            profile_id="shared_profile",
            tenant_id="isolation-tenant-B",
        )

        kg_a.upsert_node("a-page", {"title": "A-page"})
        kg_b.upsert_node("b-page", {"title": "B-page"})

        viz_a = json.loads(kg_a.export_visualization("graphml"))
        viz_b = json.loads(kg_b.export_visualization("graphml"))

        a_ids = {n["id"] for n in viz_a["nodes"]}
        b_ids = {n["id"] for n in viz_b["nodes"]}

        # Each tenant's sync export sees only its own pages — pre-W31 both
        # would have observed the union {a-page, b-page}.
        assert a_ids == {"a-page"}
        assert b_ids == {"b-page"}

    def test_node_count_is_tenant_scoped(self, tmp_path):
        """node_count returns only the calling tenant's row count.

        Pre-W31 this returned the union across tenants under the same profile,
        making downstream "pages_synced" totals overstate per-tenant scope.
        """
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        kg_a = SqliteKnowledgeGraphBackend(
            data_dir=tmp_path / "shared",
            profile_id="shared_profile",
            tenant_id="isolation-tenant-A",
        )
        kg_b = SqliteKnowledgeGraphBackend(
            data_dir=tmp_path / "shared",
            profile_id="shared_profile",
            tenant_id="isolation-tenant-B",
        )

        kg_a.upsert_node("a1", {})
        kg_a.upsert_node("a2", {})
        kg_b.upsert_node("b1", {})

        assert kg_a.node_count() == 2
        assert kg_b.node_count() == 1
