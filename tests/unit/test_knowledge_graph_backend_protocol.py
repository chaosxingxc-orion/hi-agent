"""Unit: LongTermMemoryGraph (JsonGraphBackend) satisfies KnowledgeGraphBackend Protocol."""

from __future__ import annotations

import json

from hi_agent.memory.graph_backend import (
    ConflictReport,
    Edge,
    KnowledgeGraphBackend,
    Path,
)
from hi_agent.memory.long_term import JsonGraphBackend, LongTermMemoryGraph


def test_json_graph_backend_alias():
    """JsonGraphBackend is exactly LongTermMemoryGraph."""
    assert JsonGraphBackend is LongTermMemoryGraph


def test_json_graph_backend_is_kg_backend(tmp_path):
    """LongTermMemoryGraph satisfies the KnowledgeGraphBackend runtime_checkable Protocol."""
    graph = LongTermMemoryGraph(str(tmp_path / "graph.json"))
    assert isinstance(graph, KnowledgeGraphBackend)


def test_upsert_node_inserts_new_node(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("n1", {"content": "hello world", "node_type": "fact"})
    assert graph.node_count() == 1
    node = graph.get_node("n1")
    assert node is not None
    assert node.content == "hello world"


def test_upsert_node_updates_existing_node(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("n1", {"content": "original"})
    graph.upsert_node("n1", {"content": "updated"})
    assert graph.node_count() == 1
    assert graph.get_node("n1").content == "updated"


def test_upsert_edge_creates_edge(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("a", {"content": "node a"})
    graph.upsert_node("b", {"content": "node b"})
    graph.upsert_edge("a", "b", "supports", {})
    assert graph.edge_count() == 1


def test_upsert_edge_deduplicates(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("a", {"content": "a"})
    graph.upsert_node("b", {"content": "b"})
    graph.upsert_edge("a", "b", "supports", {"weight": 1.0})
    graph.upsert_edge("a", "b", "supports", {"weight": 2.0})
    assert graph.edge_count() == 1


def test_query_relation_outgoing(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("a", {"content": "a"})
    graph.upsert_node("b", {"content": "b"})
    graph.upsert_edge("a", "b", "supports", {})
    edges = graph.query_relation("a", "supports", "out")
    assert len(edges) == 1
    assert isinstance(edges[0], Edge)
    assert edges[0].src == "a"
    assert edges[0].dst == "b"


def test_query_relation_incoming(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("a", {"content": "a"})
    graph.upsert_node("b", {"content": "b"})
    graph.upsert_edge("a", "b", "supports", {})
    edges = graph.query_relation("b", "supports", "in")
    assert len(edges) == 1
    assert edges[0].dst == "b"


def test_transitive_query_returns_paths(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("a", {"content": "a"})
    graph.upsert_node("b", {"content": "b"})
    graph.upsert_edge("a", "b", "leads_to", {})
    paths = graph.transitive_query("a", "leads_to", max_depth=3)
    assert len(paths) >= 1
    assert isinstance(paths[0], Path)


def test_detect_conflict_no_conflict(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("c1", {"content": "claim 1"})
    graph.upsert_node("c2", {"content": "claim 2"})
    result = graph.detect_conflict("c1", "c2")
    assert result is None


def test_detect_conflict_with_contradicts_edge(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("c1", {"content": "claim 1"})
    graph.upsert_node("c2", {"content": "claim 2"})
    graph.upsert_edge("c1", "c2", "contradicts", {})
    result = graph.detect_conflict("c1", "c2")
    assert result is not None
    assert isinstance(result, ConflictReport)
    assert result.conflict_type == "contradicts"


def test_export_visualization_returns_json(tmp_path):
    graph = LongTermMemoryGraph(base_dir=str(tmp_path))
    graph.upsert_node("n1", {"content": "test"})
    viz = graph.export_visualization("graphml")
    data = json.loads(viz)
    assert "nodes" in data
    assert "edges" in data
    assert data["format"] == "graphml"
