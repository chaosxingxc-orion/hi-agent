"""Tests for RetrievalEngine index governance and LongTermMemoryGraph public API."""

from __future__ import annotations

import asyncio

import pytest

from hi_agent.knowledge.retrieval_engine import RetrievalEngine
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode


# ---------------------------------------------------------------------------
# LongTermMemoryGraph public API
# ---------------------------------------------------------------------------


def _make_graph_with_nodes(n: int = 3) -> LongTermMemoryGraph:
    g = LongTermMemoryGraph()
    for i in range(n):
        node = MemoryNode(
            node_id=f"n{i}",
            content=f"content {i}",
            node_type="fact",
            confidence=0.9,
            source_sessions=[],
            tags=[],
        )
        g.add_node(node)
    return g


def test_iter_nodes_yields_all() -> None:
    """iter_nodes() returns the same count as node_count()."""
    g = _make_graph_with_nodes(3)
    items = list(g.iter_nodes())
    assert len(items) == g.node_count() == 3


def test_iter_nodes_yields_tuples() -> None:
    """iter_nodes() yields (node_id, MemoryNode) tuples."""
    g = _make_graph_with_nodes(2)
    for node_id, node in g.iter_nodes():
        assert isinstance(node_id, str)
        assert isinstance(node, MemoryNode)
        assert node.node_id == node_id


def test_stats_returns_dict() -> None:
    """stats() returns a dict with node_count and edge_count keys."""
    g = _make_graph_with_nodes(4)
    s = g.stats()
    assert isinstance(s, dict)
    assert s["node_count"] == 4
    assert s["edge_count"] == 0


# ---------------------------------------------------------------------------
# RetrievalEngine index governance
# ---------------------------------------------------------------------------


def test_index_dirty_on_construction() -> None:
    """RetrievalEngine._index_dirty is True before first build."""
    eng = RetrievalEngine()
    assert eng._index_dirty is True


def test_index_fingerprint_set_after_build() -> None:
    """_index_fingerprint is populated after build_index()."""
    eng = RetrievalEngine()
    eng.build_index()
    assert isinstance(eng._index_fingerprint, str)


def test_mark_index_dirty_resets_indexed_flag() -> None:
    """mark_index_dirty() causes the next build_index call to rebuild."""
    eng = RetrievalEngine()
    eng.build_index()
    assert eng._indexed is True
    eng.mark_index_dirty()
    assert eng._indexed is False
    assert eng._index_dirty is True
    # Rebuild succeeds
    eng.build_index()
    assert eng._indexed is True


@pytest.mark.asyncio
async def test_warm_index_async_returns_doc_count() -> None:
    """warm_index_async() returns a non-negative integer."""
    eng = RetrievalEngine()
    count = await eng.warm_index_async()
    assert isinstance(count, int)
    assert count >= 0


@pytest.mark.asyncio
async def test_warm_index_async_idempotent() -> None:
    """Calling warm_index_async() twice returns the same count."""
    eng = RetrievalEngine()
    c1 = await eng.warm_index_async()
    c2 = await eng.warm_index_async()
    assert c1 == c2
