"""Unit tests for F-3: consolidate() must call graph.save() after adding nodes."""
from pathlib import Path

from hi_agent.memory.long_term import LongTermConsolidator, LongTermMemoryGraph
from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore


def _make_mid_term_with_summary(
    storage_dir: Path, key_learnings: list[str]
) -> MidTermMemoryStore:
    """Helper: create a MidTermMemoryStore and save one DailySummary into it."""
    store = MidTermMemoryStore(storage_dir=str(storage_dir))
    summary = DailySummary(
        date="2026-04-15",
        key_learnings=key_learnings,
    )
    store.save(summary)
    return store


def test_f3_consolidate_saves_graph_to_disk(tmp_path: Path) -> None:
    """consolidate() must persist nodes to disk so they survive process restart."""
    mid_dir = tmp_path / "mid"
    graph_path = tmp_path / "graph.json"

    mid_term = _make_mid_term_with_summary(mid_dir, ["learning A"])
    graph = LongTermMemoryGraph(storage_path=str(graph_path))
    consolidator = LongTermConsolidator(mid_term_store=mid_term, graph=graph)

    count = consolidator.consolidate(days=365)

    assert count > 0, "Expected at least one node to be added"
    assert graph_path.exists(), "graph.json must be written to disk after consolidate()"

    # Load a fresh instance from the same file to confirm persistence
    new_graph = LongTermMemoryGraph(storage_path=str(graph_path))
    assert len(new_graph._nodes) > 0, "Reloaded graph must contain persisted nodes"


def test_f3_consolidate_no_save_when_no_summaries(tmp_path: Path) -> None:
    """consolidate() must not create the graph file when no summaries exist."""
    mid_dir = tmp_path / "mid"
    graph_path = tmp_path / "graph.json"

    # Empty store — no summaries saved
    mid_term = MidTermMemoryStore(storage_dir=str(mid_dir))
    graph = LongTermMemoryGraph(storage_path=str(graph_path))
    consolidator = LongTermConsolidator(mid_term_store=mid_term, graph=graph)

    count = consolidator.consolidate(days=7)

    assert count == 0
    assert not graph_path.exists(), "No file should be written when count == 0"


def test_f3_consolidate_returns_node_count(tmp_path: Path) -> None:
    """consolidate() return value must equal the number of nodes added."""
    mid_dir = tmp_path / "mid"
    graph_path = tmp_path / "graph.json"

    mid_term = _make_mid_term_with_summary(
        mid_dir, ["learning one", "learning two"]
    )
    graph = LongTermMemoryGraph(storage_path=str(graph_path))
    consolidator = LongTermConsolidator(mid_term_store=mid_term, graph=graph)

    count = consolidator.consolidate(days=365)

    assert count == 2, f"Expected 2 nodes (one per key_learning), got {count}"
