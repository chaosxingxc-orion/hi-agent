"""Unit tests for SqliteKnowledgeGraphBackend.

Layer 1 — Unit: one function per test; SQLite :memory: used in place of disk
(no external dependencies; in-memory is not a network mock).
"""

from __future__ import annotations

import pytest
from hi_agent.knowledge.sqlite_backend import SqliteKnowledgeGraphBackend
from hi_agent.memory.graph_backend import ConflictReport, Edge, Path


@pytest.fixture()
def backend() -> SqliteKnowledgeGraphBackend:
    """In-memory SQLite backend for test isolation."""
    return SqliteKnowledgeGraphBackend(db_path=":memory:")


def test_upsert_and_query_node(backend: SqliteKnowledgeGraphBackend) -> None:
    """Upserting a node and querying its outgoing relation returns the edge."""
    backend.upsert_node("n1", {"content": "node one", "tenant_id": "t1"})
    backend.upsert_node("n2", {"content": "node two", "tenant_id": "t1"})
    backend.upsert_edge("n1", "n2", "supports", {"tenant_id": "t1"})

    edges = backend.query_relation("n1", "supports", "out")
    assert len(edges) == 1
    assert isinstance(edges[0], Edge)
    assert edges[0].src == "n1"
    assert edges[0].dst == "n2"
    assert edges[0].relation == "supports"


def test_upsert_node_replaces_existing(backend: SqliteKnowledgeGraphBackend) -> None:
    """INSERT OR REPLACE semantics: second upsert overwrites the first."""
    backend.upsert_node("n1", {"content": "original", "tenant_id": "t1"})
    backend.upsert_node("n1", {"content": "updated", "tenant_id": "t1"})

    # Confirm only one row exists via export.
    import json
    data = json.loads(backend.export_visualization("graphml"))
    matching = [n for n in data["nodes"] if n["id"] == "n1"]
    assert len(matching) == 1
    assert matching[0]["content"] == "updated"


def test_tenant_isolation(backend: SqliteKnowledgeGraphBackend) -> None:
    """Node upserted for tenant_a is invisible when queried for tenant_b."""
    backend.upsert_node("shared_id", {"content": "tenant a node", "tenant_id": "tenant_a"})
    backend.upsert_node("other_id", {"content": "tenant b node", "tenant_id": "tenant_b"})
    backend.upsert_edge("shared_id", "other_id", "links", {"tenant_id": "tenant_a"})

    # Query from tenant_a's node perspective — should find the edge.
    edges_a = backend.query_relation("shared_id", "links", "out")
    assert len(edges_a) == 1

    # Query from tenant_b's node perspective — should find nothing (different tenant_id).
    edges_b = backend.query_relation("other_id", "links", "out")
    assert len(edges_b) == 0


def test_transitive_query(backend: SqliteKnowledgeGraphBackend) -> None:
    """Transitive BFS: A→B→C chain returns a Path reaching C from A."""
    for nid in ("A", "B", "C"):
        backend.upsert_node(nid, {"tenant_id": "t1"})
    backend.upsert_edge("A", "B", "leads_to", {"tenant_id": "t1"})
    backend.upsert_edge("B", "C", "leads_to", {"tenant_id": "t1"})

    paths = backend.transitive_query("A", "leads_to", max_depth=5)
    assert isinstance(paths, list)
    # Both B and C should be reachable.
    reached = {p.nodes[-1] for p in paths}
    assert "B" in reached
    assert "C" in reached
    for p in paths:
        assert isinstance(p, Path)


def test_transitive_query_respects_max_depth(backend: SqliteKnowledgeGraphBackend) -> None:
    """With max_depth=1 only direct neighbours are reachable."""
    for nid in ("A", "B", "C"):
        backend.upsert_node(nid, {"tenant_id": "t1"})
    backend.upsert_edge("A", "B", "leads_to", {"tenant_id": "t1"})
    backend.upsert_edge("B", "C", "leads_to", {"tenant_id": "t1"})

    paths = backend.transitive_query("A", "leads_to", max_depth=1)
    reached = {p.nodes[-1] for p in paths}
    assert "B" in reached
    assert "C" not in reached


def test_detect_conflict_no_conflict(backend: SqliteKnowledgeGraphBackend) -> None:
    """detect_conflict returns None when no 'contradicts' edge exists."""
    backend.upsert_node("c1", {"tenant_id": "t1"})
    backend.upsert_node("c2", {"tenant_id": "t1"})
    result = backend.detect_conflict("c1", "c2")
    assert result is None


def test_detect_conflict_with_contradicts_edge(backend: SqliteKnowledgeGraphBackend) -> None:
    """detect_conflict returns ConflictReport when a contradicts edge exists."""
    backend.upsert_node("c1", {"tenant_id": "t1"})
    backend.upsert_node("c2", {"tenant_id": "t1"})
    backend.upsert_edge("c1", "c2", "contradicts", {"tenant_id": "t1"})

    result = backend.detect_conflict("c1", "c2")
    assert result is not None
    assert isinstance(result, ConflictReport)
    assert result.conflict_type == "contradicts"
    assert result.claim_a == "c1"
    assert result.claim_b == "c2"


def test_detect_conflict_reversed_edge(backend: SqliteKnowledgeGraphBackend) -> None:
    """detect_conflict finds the conflict regardless of edge direction."""
    backend.upsert_node("c1", {"tenant_id": "t1"})
    backend.upsert_node("c2", {"tenant_id": "t1"})
    backend.upsert_edge("c2", "c1", "contradicts", {"tenant_id": "t1"})

    result = backend.detect_conflict("c1", "c2")
    assert result is not None


def test_export_visualization(backend: SqliteKnowledgeGraphBackend) -> None:
    """export_visualization returns JSON with nodes and edges keys."""
    import json

    backend.upsert_node("n1", {"content": "test", "tenant_id": "t1"})
    backend.upsert_node("n2", {"content": "test2", "tenant_id": "t1"})
    backend.upsert_edge("n1", "n2", "supports", {"tenant_id": "t1"})

    raw = backend.export_visualization("graphml")
    data = json.loads(raw)
    assert "nodes" in data
    assert "edges" in data
    assert data["format"] == "graphml"
    node_ids = {n["id"] for n in data["nodes"]}
    assert "n1" in node_ids
    assert "n2" in node_ids
    assert len(data["edges"]) == 1


def test_export_visualization_cytoscape(backend: SqliteKnowledgeGraphBackend) -> None:
    """export_visualization reflects the requested format in the output."""
    import json

    raw = backend.export_visualization("cytoscape")
    data = json.loads(raw)
    assert data["format"] == "cytoscape"


def test_query_relation_incoming(backend: SqliteKnowledgeGraphBackend) -> None:
    """direction='in' returns edges where node_id is the destination."""
    backend.upsert_node("a", {"tenant_id": "t1"})
    backend.upsert_node("b", {"tenant_id": "t1"})
    backend.upsert_edge("a", "b", "supports", {"tenant_id": "t1"})

    edges = backend.query_relation("b", "supports", "in")
    assert len(edges) == 1
    assert edges[0].dst == "b"
    assert edges[0].src == "a"


def test_query_relation_both(backend: SqliteKnowledgeGraphBackend) -> None:
    """direction='both' returns outgoing and incoming edges."""
    backend.upsert_node("a", {"tenant_id": "t1"})
    backend.upsert_node("b", {"tenant_id": "t1"})
    backend.upsert_node("c", {"tenant_id": "t1"})
    backend.upsert_edge("a", "b", "links", {"tenant_id": "t1"})
    backend.upsert_edge("c", "a", "links", {"tenant_id": "t1"})

    edges = backend.query_relation("a", "links", "both")
    assert len(edges) == 2
