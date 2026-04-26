"""Integration test: SqliteKnowledgeGraphBackend survives a close + reopen.

Layer 2 — Integration: real SQLite file on disk; close() then construct
a new instance from the same path and assert that written data is present.
This satisfies Rule 8 durable-store requirement for research/prod posture.
"""

from __future__ import annotations

import json

from hi_agent.knowledge.sqlite_backend import SqliteKnowledgeGraphBackend


def test_write_then_restart_query_returns(tmp_path) -> None:
    """Data written to SqliteKnowledgeGraphBackend persists across close/reopen."""
    db_path = str(tmp_path / "kg.db")

    # Phase 1: write
    backend = SqliteKnowledgeGraphBackend(db_path=db_path)
    backend.upsert_node("node_persist", {"content": "durable", "tenant_id": "t1"})
    backend.upsert_node("node_b", {"content": "b side", "tenant_id": "t1"})
    backend.upsert_edge("node_persist", "node_b", "relates_to", {"tenant_id": "t1"})
    backend.close()

    # Phase 2: reopen — simulate restart by constructing a new instance.
    backend2 = SqliteKnowledgeGraphBackend(db_path=db_path)
    edges = backend2.query_relation("node_persist", "relates_to", "out")
    assert len(edges) == 1
    assert edges[0].dst == "node_b"

    raw = backend2.export_visualization("graphml")
    data = json.loads(raw)
    node_ids = {n["id"] for n in data["nodes"]}
    assert "node_persist" in node_ids
    assert "node_b" in node_ids
    backend2.close()


def test_upsert_edge_survives_restart(tmp_path) -> None:
    """Edges written before close are present after reopening the same file."""
    db_path = str(tmp_path / "kg_edges.db")

    backend = SqliteKnowledgeGraphBackend(db_path=db_path)
    backend.upsert_node("src", {"tenant_id": "t1"})
    backend.upsert_node("dst", {"tenant_id": "t1"})
    backend.upsert_edge("src", "dst", "supports", {"tenant_id": "t1", "weight": 0.9})
    backend.close()

    backend2 = SqliteKnowledgeGraphBackend(db_path=db_path)
    raw = backend2.export_visualization("cytoscape")
    data = json.loads(raw)
    assert len(data["edges"]) == 1
    assert data["edges"][0]["src"] == "src"
    assert data["edges"][0]["dst"] == "dst"
    backend2.close()
