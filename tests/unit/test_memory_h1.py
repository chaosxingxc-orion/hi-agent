"""Tests for H-1: TF-IDF semantic search + embedding_fn in LongTermMemoryGraph."""

from __future__ import annotations

from pathlib import Path

import pytest
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode


def _make_node(node_id: str, content: str, **kwargs) -> MemoryNode:
    return MemoryNode(node_id=node_id, content=content, **kwargs)


def test_h1_tfidf_ranks_relevant_higher(tmp_path: Path) -> None:
    """TF-IDF ranks a node whose content matches query terms above an unrelated one."""
    g = LongTermMemoryGraph(storage_path=str(tmp_path / "g.json"))
    g.add_node(_make_node("n1", "machine learning neural network training"))
    g.add_node(_make_node("n2", "cooking recipe pasta tomato sauce"))

    results = g.search("neural network")
    assert len(results) >= 1
    assert results[0].node_id == "n1", "Relevant node must rank first"


def test_h1_tfidf_index_rebuilt_on_load(tmp_path: Path) -> None:
    """After save+load, TF-IDF index is rebuilt and search still works."""
    graph_file = str(tmp_path / "g2.json")
    g1 = LongTermMemoryGraph(storage_path=graph_file)
    g1.add_node(_make_node("n1", "python asyncio coroutine event loop"))
    g1.add_node(_make_node("n2", "database sql schema migration"))
    g1.save()

    g2 = LongTermMemoryGraph(storage_path=graph_file)
    results = g2.search("asyncio coroutine")
    assert results[0].node_id == "n1"


def test_h1_embedding_fn_used_when_provided() -> None:
    """When embedding_fn is set, it is called during search."""
    call_log: list[str] = []

    def fake_embed(text: str) -> list[float]:
        call_log.append(text)
        # Return a unit vector based on whether text contains 'cat'
        return [1.0, 0.0] if "cat" in text.lower() else [0.0, 1.0]

    g = LongTermMemoryGraph(embedding_fn=fake_embed)
    g.add_node(_make_node("n1", "cat and dog"))
    g.add_node(_make_node("n2", "car and bus"))

    call_log.clear()
    results = g.search("cat")
    # embedding_fn must have been called for both the query and at least one node
    assert len(call_log) >= 2
    assert results[0].node_id == "n1", "Cat node should rank higher for 'cat' query"


def test_h1_keyword_fallback_when_index_empty() -> None:
    """When TF-IDF index is empty (no nodes), falls back gracefully."""
    g = LongTermMemoryGraph()
    results = g.search("anything")
    assert results == []


def test_h1_cosine_similarity_correct() -> None:
    """Cosine similarity between identical vectors == 1, orthogonal == 0."""
    from hi_agent.memory.long_term import _cosine

    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


def test_h1_new_constructor_signature_backward_compatible(tmp_path: Path) -> None:
    """Existing callers that pass only storage_path and profile_id still work."""
    g1 = LongTermMemoryGraph()
    g2 = LongTermMemoryGraph(storage_path=str(tmp_path / "g.json"))
    g3 = LongTermMemoryGraph(
        storage_path=str(tmp_path / "base" / "memory" / "long_term" / "graph.json"),
        profile_id="user-123",
    )
    assert g1.node_count() == 0
    assert g2.node_count() == 0
    assert g3.node_count() == 0
