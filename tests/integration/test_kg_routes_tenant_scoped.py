"""Integration: SQLite KG backend enforces profile + tenant isolation.

Layer 2 — Integration test. Uses real SqliteKnowledgeGraphBackend instances.
No mocks on the subsystem under test.

W31 (T-4'): backend now also filters by tenant_id at every read.  Tests
construct the backend directly with explicit ``tenant_id=`` so the
per-tenant WHERE filter is exercised end-to-end.
"""

from __future__ import annotations

from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend


def _build_sqlite_graph(
    *, data_dir, profile_id: str, tenant_id: str
) -> SqliteKnowledgeGraphBackend:
    """Build a tenant-scoped SQLite KG backend (research-posture compatible)."""
    return SqliteKnowledgeGraphBackend(
        data_dir=data_dir,
        profile_id=profile_id,
        tenant_id=tenant_id,
    )


def test_tenant_a_data_not_visible_to_tenant_b(tmp_path):
    """Nodes written for tenant A are invisible when queried as tenant B.

    Both backends share the same SQLite file (same data_dir + profile_id) but
    use different tenant_id scopes — verifies the W31 T-4' WHERE filter.
    """
    # Same profile_id + same data_dir; only tenant_id differs.  This is the
    # scenario where the W31 fix is decisive: pre-W31 rows under one profile
    # leaked across tenants because tenant_id was not in the WHERE clause.
    graph_a = _build_sqlite_graph(
        data_dir=tmp_path / "shared", profile_id="shared_profile", tenant_id="tenant_a"
    )
    graph_b = _build_sqlite_graph(
        data_dir=tmp_path / "shared", profile_id="shared_profile", tenant_id="tenant_b"
    )

    # Ingest data as tenant A.
    graph_a.upsert_node(
        "secret_node", {"content": "tenant A secret", "node_type": "fact", "tags": []}
    )
    assert graph_a.node_count() == 1

    # Tenant B must see zero nodes (W31 T-4' WHERE filter).
    assert graph_b.node_count() == 0, (
        "Tenant B can see tenant A's nodes — W31 tenant_id WHERE filter is broken."
    )

    # Tenant B search must return empty.
    results = graph_b.search("tenant A secret", limit=10)
    assert results == [], (
        "Tenant B search returned tenant A's data — isolation is broken."
    )


def test_cross_tenant_edge_query_returns_empty(tmp_path):
    """Edges written for tenant A are not returned when queried as tenant B."""
    graph_a = _build_sqlite_graph(
        data_dir=tmp_path / "shared", profile_id="shared_profile", tenant_id="tenant_a_edges"
    )
    graph_b = _build_sqlite_graph(
        data_dir=tmp_path / "shared", profile_id="shared_profile", tenant_id="tenant_b_edges"
    )

    graph_a.upsert_node("n1", {"content": "a", "node_type": "fact", "tags": []})
    graph_a.upsert_node("n2", {"content": "b", "node_type": "fact", "tags": []})
    graph_a.upsert_edge("n1", "n2", "supports", {"weight": 1.0})

    edges_b = graph_b.query_relation("n1", "supports", "out")
    assert edges_b == [], (
        "Tenant B can query tenant A's edges — isolation is broken."
    )


def test_same_node_id_different_profiles_coexist(tmp_path):
    """Same node_id under different (profile, tenant) pairs coexist without collision.

    The primary key on kg_nodes is (node_id, profile_id, project_id), so two
    rows with the same node_id+profile_id collide regardless of tenant_id.
    Distinct profile_ids let two tenants both write their own ``shared_id``
    row; the W31 T-4' tenant_id WHERE filter then guarantees they cannot
    read each other's content.
    """
    graph_a = _build_sqlite_graph(
        data_dir=tmp_path / "shared", profile_id="profile_x", tenant_id="tenant_x"
    )
    graph_b = _build_sqlite_graph(
        data_dir=tmp_path / "shared", profile_id="profile_y", tenant_id="tenant_y"
    )

    graph_a.upsert_node(
        "shared_id", {"content": "xylophone alpha unique", "node_type": "fact", "tags": []}
    )
    graph_b.upsert_node(
        "shared_id", {"content": "zeppelin beta unique", "node_type": "fact", "tags": []}
    )

    # Each (profile, tenant) sees exactly 1 node.
    assert graph_a.node_count() == 1
    assert graph_b.node_count() == 1

    # Search results are correctly scoped.
    results_a = graph_a.search("xylophone", limit=5)
    results_b = graph_b.search("zeppelin", limit=5)
    assert any("xylophone" in r.content for r in results_a)
    assert any("zeppelin" in r.content for r in results_b)

    # Cross-check: A's search for B's unique term returns empty.
    results_a_cross = graph_a.search("zeppelin", limit=5)
    assert results_a_cross == [], (
        "Profile X / tenant X returned profile Y / tenant Y's data — isolation broken."
    )
