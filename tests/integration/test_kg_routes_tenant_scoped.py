"""Integration: SQLite KG backend enforces profile-level tenant isolation.

Layer 2 — Integration test. Uses real SqliteKnowledgeGraphBackend instances.
No mocks on the subsystem under test.

Verifies: data ingested under profile A is not visible under profile B,
satisfying the tenant-scoping requirement (Rule 12 — Contract Spine Completeness).
"""

from __future__ import annotations

import os
from unittest.mock import patch

from hi_agent.config.memory_builder import MemoryBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend


def _build_sqlite_graph(builder: MemoryBuilder, profile_id: str) -> SqliteKnowledgeGraphBackend:
    with patch.dict(
        os.environ,
        {"HI_AGENT_POSTURE": "research", "HI_AGENT_KG_BACKEND": ""},
        clear=False,
    ):
        graph = builder.build_long_term_graph(profile_id=profile_id)
    assert isinstance(graph, SqliteKnowledgeGraphBackend)
    return graph


def test_tenant_a_data_not_visible_to_tenant_b(tmp_path):
    """Nodes written for profile A are invisible when queried as profile B.

    Both backends share the same SQLite file (same data_dir) but use different
    profile_id scopes. This is the primary tenant-isolation guarantee.
    """
    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))

    # Two separate MemoryBuilder instances, each with a distinct profile.
    builder_a = MemoryBuilder(config)
    builder_b = MemoryBuilder(config)

    graph_a = _build_sqlite_graph(builder_a, "tenant_a")
    graph_b = _build_sqlite_graph(builder_b, "tenant_b")

    # Ingest data as tenant A.
    graph_a.upsert_node(
        "secret_node", {"content": "tenant A secret", "node_type": "fact", "tags": []}
    )
    assert graph_a.node_count() == 1

    # Tenant B must see zero nodes.
    assert graph_b.node_count() == 0, (
        "Tenant B can see tenant A's nodes — profile isolation is broken."
    )

    # Tenant B search must return empty.
    results = graph_b.search("tenant A secret", limit=10)
    assert results == [], (
        "Tenant B search returned tenant A's data — isolation is broken."
    )


def test_cross_tenant_edge_query_returns_empty(tmp_path):
    """Edges written for profile A are not returned when queried as profile B."""
    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))

    builder_a = MemoryBuilder(config)
    builder_b = MemoryBuilder(config)

    graph_a = _build_sqlite_graph(builder_a, "tenant_a_edges")
    graph_b = _build_sqlite_graph(builder_b, "tenant_b_edges")

    graph_a.upsert_node("n1", {"content": "a", "node_type": "fact", "tags": []})
    graph_a.upsert_node("n2", {"content": "b", "node_type": "fact", "tags": []})
    graph_a.upsert_edge("n1", "n2", "supports", {"weight": 1.0})

    edges_b = graph_b.query_relation("n1", "supports", "out")
    assert edges_b == [], (
        "Tenant B can query tenant A's edges — isolation is broken."
    )


def test_same_node_id_different_profiles_coexist(tmp_path):
    """Same node_id under different profiles must coexist without collision."""
    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))

    builder_a = MemoryBuilder(config)
    builder_b = MemoryBuilder(config)

    graph_a = _build_sqlite_graph(builder_a, "profile_x")
    graph_b = _build_sqlite_graph(builder_b, "profile_y")

    graph_a.upsert_node(
        "shared_id", {"content": "xylophone alpha unique", "node_type": "fact", "tags": []}
    )
    graph_b.upsert_node(
        "shared_id", {"content": "zeppelin beta unique", "node_type": "fact", "tags": []}
    )

    # Each profile sees exactly 1 node.
    assert graph_a.node_count() == 1
    assert graph_b.node_count() == 1

    # Search results are correctly scoped by profile.
    results_a = graph_a.search("xylophone", limit=5)
    results_b = graph_b.search("zeppelin", limit=5)
    assert any("xylophone" in r.content for r in results_a)
    assert any("zeppelin" in r.content for r in results_b)

    # Cross-check: A's search for B's unique term returns empty.
    results_a_cross = graph_a.search("zeppelin", limit=5)
    assert results_a_cross == [], (
        "Profile X returned profile Y's data — profile isolation is broken."
    )
