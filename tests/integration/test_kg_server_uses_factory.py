"""Integration: KG SQLite backend survives restart (data durability).

Layer 2 — Integration test. Uses real SqliteKnowledgeGraphBackend
directly. No mocks on the subsystem under test.

Verifies: data written in session 1 is readable in session 2
(restart-survival requirement from Rule 8 / RO track).

W31 (T-4'): the backend requires an explicit tenant_id under research/prod
posture (raises ValueError if empty), so each construction here passes
``tenant_id=`` so the per-tenant WHERE filter is exercised on every read.
"""

from __future__ import annotations

from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

_TEST_TENANT = "test_tenant"


def _open_backend(data_dir, profile_id: str) -> SqliteKnowledgeGraphBackend:
    """Open a SQLite KG backend rooted at *data_dir* with an explicit tenant."""
    return SqliteKnowledgeGraphBackend(
        data_dir=data_dir,
        profile_id=profile_id,
        tenant_id=_TEST_TENANT,
    )


def test_data_survives_new_builder_instance(tmp_path):
    """Data written via one backend instance is readable by a new instance."""
    profile_id = "restart_test_profile"

    # Session 1: write data.
    graph1 = _open_backend(tmp_path, profile_id)
    graph1.upsert_node("node1", {"content": "durable fact", "node_type": "fact", "tags": []})
    graph1.upsert_node("node2", {"content": "another fact", "node_type": "fact", "tags": []})
    graph1.upsert_edge("node1", "node2", "supports", {"weight": 1.0})

    assert graph1.node_count() == 2
    assert graph1.edge_count() == 1

    # Session 2: fresh backend instance over the same SQLite file (simulates restart).
    graph2 = _open_backend(tmp_path, profile_id)

    # Data must survive.
    assert graph2.node_count() == 2, "node_count dropped after restart"
    assert graph2.edge_count() == 1, "edge_count dropped after restart"

    edges = graph2.query_relation("node1", "supports", "out")
    assert len(edges) == 1
    assert edges[0].dst == "node2"


def test_search_returns_matching_nodes_from_sqlite(tmp_path):
    """Search over SQLite backend returns matching nodes."""
    graph = _open_backend(tmp_path, "search_profile")

    graph.upsert_node(
        "n1", {"content": "python async programming", "node_type": "fact", "tags": []}
    )
    graph.upsert_node("n2", {
        "content": "database indexing patterns", "node_type": "fact", "tags": [],
    })

    results = graph.search("python async", limit=10)
    assert len(results) >= 1
    contents = [r.content for r in results]
    assert any("python" in c.lower() for c in contents)


def test_upsert_node_idempotent(tmp_path):
    """Upserting the same node twice does not create a duplicate."""
    graph = _open_backend(tmp_path, "idempotent_profile")

    graph.upsert_node("n1", {"content": "first version", "node_type": "fact", "tags": []})
    graph.upsert_node("n1", {"content": "updated version", "node_type": "fact", "tags": []})

    assert graph.node_count() == 1


def test_detect_conflict_via_sqlite(tmp_path):
    """detect_conflict finds contradicts edges in SQLite backend."""
    graph = _open_backend(tmp_path, "conflict_profile")

    graph.upsert_node("c1", {"content": "claim 1", "node_type": "fact", "tags": []})
    graph.upsert_node("c2", {"content": "claim 2", "node_type": "fact", "tags": []})
    graph.upsert_edge("c1", "c2", "contradicts", {})

    report = graph.detect_conflict("c1", "c2")
    assert report is not None
    assert report.conflict_type == "contradicts"


def test_export_visualization_sqlite(tmp_path):
    """export_visualization returns valid JSON from SQLite backend."""
    import json

    graph = _open_backend(tmp_path, "viz_profile")

    graph.upsert_node("n1", {"content": "node content", "node_type": "fact", "tags": []})
    viz = graph.export_visualization("graphml")
    data = json.loads(viz)
    assert "nodes" in data and "edges" in data
    assert data["format"] == "graphml"
