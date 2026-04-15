"""Unit tests for L3 long-term memory graph profile_id path isolation."""

from __future__ import annotations

from pathlib import Path

from hi_agent.memory.long_term import LongTermMemoryGraph


def test_different_profile_ids_use_different_paths() -> None:
    """Two graphs with different profile_ids must resolve to different storage paths."""
    g1 = LongTermMemoryGraph(
        storage_path=".hi_agent/memory/long_term/graph.json",
        profile_id="profile-alpha",
    )
    g2 = LongTermMemoryGraph(
        storage_path=".hi_agent/memory/long_term/graph.json",
        profile_id="profile-beta",
    )

    assert g1._storage_path != g2._storage_path
    assert "profile-alpha" in str(g1._storage_path)
    assert "profile-beta" in str(g2._storage_path)


def test_profile_id_path_contains_L3_segment() -> None:
    """profile_id path must include the L3 namespace segment."""
    g = LongTermMemoryGraph(
        storage_path=".hi_agent/memory/long_term/graph.json",
        profile_id="user-42",
    )
    parts = Path(g._storage_path).parts
    assert "L3" in parts
    assert "user-42" in parts
    assert parts[-1] == "graph.json"


def test_no_profile_id_uses_default_path() -> None:
    """A graph without profile_id keeps the original storage_path unchanged."""
    default = ".hi_agent/memory/long_term/graph.json"
    g = LongTermMemoryGraph(storage_path=default)

    assert g._storage_path == Path(default)


def test_no_profile_id_uses_constructor_default() -> None:
    """Calling LongTermMemoryGraph() with no args uses the hardcoded default."""
    g = LongTermMemoryGraph()

    assert g._storage_path == Path(".hi_agent/memory/long_term/graph.json")


def test_profile_id_path_structure(tmp_path: Path) -> None:
    """End-to-end: save/load round-trip for a profile-scoped graph."""
    from hi_agent.memory.long_term import MemoryNode

    storage_path = str(tmp_path / "memory" / "long_term" / "graph.json")
    g = LongTermMemoryGraph(storage_path=storage_path, profile_id="proj-1")

    expected = tmp_path / "memory" / "L3" / "proj-1" / "graph.json"
    assert g._storage_path == expected

    node = MemoryNode(node_id="n1", content="test fact", node_type="fact")
    g.add_node(node)
    g.save()

    assert expected.exists()

    g2 = LongTermMemoryGraph(storage_path=storage_path, profile_id="proj-1")
    g2.load()
    assert g2.node_count() == 1
    assert g2.get_node("n1") is not None
