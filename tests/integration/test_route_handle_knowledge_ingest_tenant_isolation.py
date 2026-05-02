"""Tenant isolation: KG ingest path is tenant-scoped at the store (W31 T-4').

Pre-W31: ``SqliteKnowledgeGraphBackend`` writes carried tenant_id in the row
but reads ignored it; this file pins the new scoping invariants on the store
side (A3 territory).  Route-layer plumbing is owned by A2.

Layer 2 — Integration: real ``SqliteKnowledgeGraphBackend`` instances.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestKnowledgeIngestTenantIsolation:
    """KG ingest writes are visible only inside the writing tenant (W31 T-4')."""

    def test_tenant_b_node_count_does_not_include_tenant_a_writes(self, tmp_path):
        """Tenant A and B writing under the same profile see only their own counts."""
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

        kg_a.upsert_node(
            "shared_id_a",
            {"content": "alpha-secret-AAA", "node_type": "fact", "tags": []},
        )
        kg_b.upsert_node(
            "shared_id_b",
            {"content": "bravo-payload-BBB", "node_type": "fact", "tags": []},
        )

        # Each tenant sees exactly its own write.
        assert kg_a.node_count() == 1, "tenant A should see only its own node"
        assert kg_b.node_count() == 1, "tenant B should see only its own node"

        # Cross-tenant search is empty (W31 T-4' tenant_id WHERE filter).
        assert kg_a.search("bravo-payload-BBB", limit=5) == [], (
            "tenant A search returned tenant B's content; W31 T-4' regression"
        )
        assert kg_b.search("alpha-secret-AAA", limit=5) == [], (
            "tenant B search returned tenant A's content; W31 T-4' regression"
        )

    def test_kg_strict_posture_rejects_empty_tenant_id(self, tmp_path, monkeypatch):
        """Under research/prod posture the backend refuses construction with empty tenant_id.

        This is the core defense-in-depth assertion: the store layer fails
        loudly rather than silently sharing rows when callers forget to pass
        tenant_id.
        """
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        for posture_name in ("research", "prod"):
            monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
            with pytest.raises(ValueError, match="tenant_id"):
                SqliteKnowledgeGraphBackend(
                    data_dir=tmp_path / posture_name,
                    profile_id="strict_profile",
                    tenant_id="",
                )
