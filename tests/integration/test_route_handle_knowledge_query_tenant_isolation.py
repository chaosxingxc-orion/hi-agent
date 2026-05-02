"""Tenant isolation: KG store query path enforces tenant_id WHERE filter (W31 T-4').

Pre-W31: ``SqliteKnowledgeGraphBackend`` filtered reads by ``profile_id`` and
``project_id`` but silently dropped ``tenant_id`` from the WHERE clause, so two
tenants sharing the same profile read each other's data.  W31 T-4' adds
``AND tenant_id = ?`` to every read query; under research/prod posture an
empty tenant_id raises ValueError at construction.

The route layer fix (A2 territory) must additionally plumb the request's
``tenant_id`` from ``TenantContext`` into every KM call so the store's
defense-in-depth fires.  This file pins the store-level behaviour; A2's
route-layer regression lives in ``tests/integration/test_routes_knowledge_*``.

Layer 2 — Integration: real ``SqliteKnowledgeGraphBackend`` instances; no
mocks on the subsystem under test.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestKnowledgeQueryTenantIsolation:
    """Knowledge query reads are scoped by tenant_id at the store layer (W31 T-4')."""

    def test_tenant_b_query_does_not_return_tenant_a_content(self, tmp_path):
        """Tenant B's KG backend cannot see content written by tenant A."""
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        unique_term = "xzq-secret-content-tenant-A-only"
        # Both backends share the data_dir + profile so only tenant_id differs.
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

        # Tenant A writes the secret content.
        kg_a.upsert_node(
            "secret-node",
            {"content": f"This contains the {unique_term}", "node_type": "fact", "tags": []},
        )
        assert kg_a.node_count() == 1
        assert kg_a.search(unique_term, limit=10), "tenant A must see its own content"

        # Tenant B sees nothing because of the W31 tenant_id WHERE filter.
        assert kg_b.node_count() == 0, (
            f"Tenant B sees tenant A's nodes (W31 T-4' regression). "
            f"node_count={kg_b.node_count()}"
        )
        assert kg_b.search(unique_term, limit=10) == [], (
            f"Tenant B's KG search returned tenant A's content for {unique_term!r}; "
            "tenant_id WHERE filter is broken."
        )

    def test_query_context_does_not_leak_cross_tenant_data(self, tmp_path):
        """edge query / transitive query / detect_conflict must not return cross-tenant rows."""
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

        kg_a.upsert_node("n1", {"content": "secret", "node_type": "fact", "tags": []})
        kg_a.upsert_node("n2", {"content": "secret-target", "node_type": "fact", "tags": []})
        kg_a.upsert_edge("n1", "n2", "supports", {"weight": 1.0})

        # Tenant B cannot query tenant A's edges.
        assert kg_b.query_relation("n1", "supports", "out") == []
        assert kg_b.query_relation("n2", "supports", "in") == []

        # Transitive query also tenant-scoped.
        assert kg_b.transitive_query("n1", "supports", max_depth=5) == []

        # detect_conflict tenant-scoped.
        kg_a.upsert_edge("n1", "n2", "contradicts", {})
        assert kg_a.detect_conflict("n1", "n2") is not None
        assert kg_b.detect_conflict("n1", "n2") is None
