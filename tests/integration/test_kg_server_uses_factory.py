"""Integration: KG SQLite backend survives restart (data durability).

Layer 2 — Integration test. Uses real SqliteKnowledgeGraphBackend
and real MemoryBuilder. No mocks on the subsystem under test.

Verifies: data written in session 1 is readable in session 2
(restart-survival requirement from Rule 8 / RO track).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from hi_agent.config.memory_builder import MemoryBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend


@pytest.fixture()
def sqlite_builder(tmp_path):
    """MemoryBuilder configured for research posture (SQLite default)."""
    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    return MemoryBuilder(config), tmp_path


def _get_sqlite_backend(builder: MemoryBuilder, profile_id: str) -> SqliteKnowledgeGraphBackend:
    """Build graph under research posture and assert SQLite backend."""
    with patch.dict(
        os.environ,
        {"HI_AGENT_POSTURE": "research", "HI_AGENT_KG_BACKEND": ""},
        clear=False,
    ):
        graph = builder.build_long_term_graph(profile_id=profile_id)
    assert isinstance(graph, SqliteKnowledgeGraphBackend), (
        f"Expected SqliteKnowledgeGraphBackend, got {type(graph).__name__}"
    )
    return graph


def test_data_survives_new_builder_instance(tmp_path):
    """Data written via one MemoryBuilder instance is readable by a new instance."""
    profile_id = "restart_test_profile"
    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))

    # Session 1: write data.
    builder1 = MemoryBuilder(config)
    graph1 = _get_sqlite_backend(builder1, profile_id)
    graph1.upsert_node("node1", {"content": "durable fact", "node_type": "fact", "tags": []})
    graph1.upsert_node("node2", {"content": "another fact", "node_type": "fact", "tags": []})
    graph1.upsert_edge("node1", "node2", "supports", {"weight": 1.0})

    assert graph1.node_count() == 2
    assert graph1.edge_count() == 1

    # Session 2: fresh builder (simulates restart).
    builder2 = MemoryBuilder(config)
    graph2 = _get_sqlite_backend(builder2, profile_id)

    # Data must survive.
    assert graph2.node_count() == 2, "node_count dropped after restart"
    assert graph2.edge_count() == 1, "edge_count dropped after restart"

    edges = graph2.query_relation("node1", "supports", "out")
    assert len(edges) == 1
    assert edges[0].dst == "node2"


def test_search_returns_matching_nodes_from_sqlite(tmp_path):
    """Search over SQLite backend returns matching nodes."""
    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    builder = MemoryBuilder(config)
    graph = _get_sqlite_backend(builder, "search_profile")

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
    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    builder = MemoryBuilder(config)
    graph = _get_sqlite_backend(builder, "idempotent_profile")

    graph.upsert_node("n1", {"content": "first version", "node_type": "fact", "tags": []})
    graph.upsert_node("n1", {"content": "updated version", "node_type": "fact", "tags": []})

    assert graph.node_count() == 1


def test_detect_conflict_via_sqlite(tmp_path):
    """detect_conflict finds contradicts edges in SQLite backend."""
    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    builder = MemoryBuilder(config)
    graph = _get_sqlite_backend(builder, "conflict_profile")

    graph.upsert_node("c1", {"content": "claim 1", "node_type": "fact", "tags": []})
    graph.upsert_node("c2", {"content": "claim 2", "node_type": "fact", "tags": []})
    graph.upsert_edge("c1", "c2", "contradicts", {})

    report = graph.detect_conflict("c1", "c2")
    assert report is not None
    assert report.conflict_type == "contradicts"


def test_export_visualization_sqlite(tmp_path):
    """export_visualization returns valid JSON from SQLite backend."""
    import json

    config = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    builder = MemoryBuilder(config)
    graph = _get_sqlite_backend(builder, "viz_profile")

    graph.upsert_node("n1", {"content": "node content", "node_type": "fact", "tags": []})
    viz = graph.export_visualization("graphml")
    data = json.loads(viz)
    assert "nodes" in data and "edges" in data
    assert data["format"] == "graphml"
