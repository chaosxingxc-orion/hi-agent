"""Tests for H-2: LongTermMemoryGraph auto-load on init."""

from __future__ import annotations

from pathlib import Path

from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode


def test_h2_auto_load_on_init(tmp_path: Path) -> None:
    """Node persisted by one instance is visible on a fresh instance without load()."""
    graph_file = str(tmp_path / "graph.json")

    g1 = LongTermMemoryGraph(storage_path=graph_file)
    node = MemoryNode(node_id="n1", content="hello world", node_type="fact")
    g1.add_node(node)
    g1.save()

    # New instance — must auto-load
    g2 = LongTermMemoryGraph(storage_path=graph_file)
    assert g2.node_count() == 1
    assert g2.get_node("n1") is not None
    assert g2.get_node("n1").content == "hello world"


def test_h2_no_error_when_file_absent(tmp_path: Path) -> None:
    """Constructor must not raise when the JSON file does not exist yet."""
    graph_file = str(tmp_path / "nonexistent" / "graph.json")
    g = LongTermMemoryGraph(storage_path=graph_file)
    assert g.node_count() == 0
