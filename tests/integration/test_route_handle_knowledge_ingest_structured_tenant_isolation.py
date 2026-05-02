"""Tenant isolation: structured-fact ingest is tenant-scoped at the store (W31 T-4').

Pre-W31: structured ingest landed in the shared kg_edges table without a
tenant_id WHERE filter on read.  W31 T-4' adds ``AND tenant_id = ?`` to every
read so two tenants writing structurally identical facts under the same
profile do not leak across.

Layer 2 — Integration: real ``SqliteKnowledgeGraphBackend`` instances.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestKnowledgeIngestStructuredTenantIsolation:
    """Structured-fact ingest reads only return rows for the calling tenant."""

    def test_tenant_b_facts_do_not_pollute_tenant_a_graph(self, tmp_path):
        """Edges written by tenant B are invisible from tenant A's KG and vice-versa."""
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

        # Tenant A and B both store nodes/edges under the same profile.  Each
        # uses its own node_id so the (node_id, profile_id, project_id) primary
        # key does not collide.
        kg_a.upsert_node("a-secret", {"content": "A-private-data", "node_type": "fact"})
        kg_a.upsert_node("a-target", {"content": "target", "node_type": "fact"})
        kg_a.upsert_edge("a-secret", "a-target", "has", {})

        kg_b.upsert_node("b-fact", {"content": "B-data", "node_type": "fact"})
        kg_b.upsert_node("b-target", {"content": "target", "node_type": "fact"})
        kg_b.upsert_edge("b-fact", "b-target", "knows", {})

        # Tenant A sees only A's edges; tenant B's "knows" edge is invisible.
        a_out = kg_a.query_relation("a-secret", "has", "out")
        assert len(a_out) == 1
        b_out_for_a = kg_a.query_relation("b-fact", "knows", "out")
        assert b_out_for_a == [], (
            "Tenant A can see Tenant B's edges (W31 T-4' WHERE filter regression)."
        )

        # Symmetric check from tenant B.
        b_out = kg_b.query_relation("b-fact", "knows", "out")
        assert len(b_out) == 1
        a_out_for_b = kg_b.query_relation("a-secret", "has", "out")
        assert a_out_for_b == [], (
            "Tenant B can see Tenant A's edges (W31 T-4' WHERE filter regression)."
        )

    def test_export_visualization_is_tenant_scoped(self, tmp_path):
        """export_visualization returns nodes/edges only for the calling tenant."""
        import json

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

        kg_a.upsert_node("a1", {"content": "A node"})
        kg_b.upsert_node("b1", {"content": "B node"})

        viz_a = json.loads(kg_a.export_visualization("graphml"))
        viz_b = json.loads(kg_b.export_visualization("graphml"))

        a_ids = {n["id"] for n in viz_a["nodes"]}
        b_ids = {n["id"] for n in viz_b["nodes"]}
        assert a_ids == {"a1"}, f"tenant A visualization should contain only a1, got {a_ids}"
        assert b_ids == {"b1"}, f"tenant B visualization should contain only b1, got {b_ids}"
