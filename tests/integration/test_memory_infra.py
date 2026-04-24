"""Unit tests for memory/session infrastructure: P-2, P-3, P-6."""

from __future__ import annotations

import tempfile

import pytest
from hi_agent.contracts.reasoning import ReasoningStep, ReasoningTrace
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryEdge, MemoryNode
from hi_agent.memory.short_term import ShortTermMemoryStore
from hi_agent.session.run_session import RunSession

# ---------------------------------------------------------------------------
# P-2: ReasoningTrace storage
# ---------------------------------------------------------------------------


def test_reasoning_trace_write() -> None:
    """write_reasoning_trace stores a ReasoningTrace as an L0 record."""
    session = RunSession(run_id="run-001")
    trace = ReasoningTrace(
        trace_id="tr-1",
        run_id="run-001",
        stage_id="plan",
        steps=[
            ReasoningStep(
                step_id="s1",
                stage_id="plan",
                action="route",
                thought="choose search route",
                timestamp="2026-01-01T00:00:00Z",
            )
        ],
    )
    session.write_reasoning_trace(trace)

    assert len(session.l0_records) == 1
    record = session.l0_records[0]
    assert record["event_type"] == "reasoning_trace"
    # stage_id in the L0 record header reflects the session's current_stage (empty
    # until explicitly set); the trace's stage is in the payload.
    payload = record["payload"]
    assert payload["trace_id"] == "tr-1"
    assert len(payload["steps"]) == 1
    assert payload["steps"][0]["action"] == "route"


# ---------------------------------------------------------------------------
# P-3: project_id scoping
# ---------------------------------------------------------------------------


def test_project_id_stored_in_run_session() -> None:
    """RunSession accepts project_id and exposes it via property."""
    session = RunSession(run_id="run-002", project_id="proj-alpha")
    assert session._project_id == "proj-alpha"
    assert session.project_id == "proj-alpha"


def test_project_id_stored_in_short_term_store() -> None:
    """ShortTermMemoryStore accepts project_id."""
    store = ShortTermMemoryStore(project_id="proj-beta")
    assert store._project_id == "proj-beta"


def test_project_id_stored_in_long_term_graph() -> None:
    """LongTermMemoryGraph accepts project_id and scopes storage path."""
    with tempfile.TemporaryDirectory() as td:
        graph = LongTermMemoryGraph(base_dir=td, profile_id="u1", project_id="proj-gamma")
        assert graph._project_id == "proj-gamma"
        # Path should include project_id directory component
        assert "proj-gamma" in str(graph._storage_path)


# ---------------------------------------------------------------------------
# P-6: Graph inference methods
# ---------------------------------------------------------------------------


def _small_graph(tmp_dir: str) -> LongTermMemoryGraph:
    """Build a 4-node graph: a→b→c, a→d (supports); a→c (contradicts)."""
    g = LongTermMemoryGraph(base_dir=tmp_dir)
    for nid, content in [("a", "alpha"), ("b", "beta"), ("c", "gamma"), ("d", "delta")]:
        g.add_node(MemoryNode(nid, content))
    g.add_edge(MemoryEdge("a", "b", "supports"))
    g.add_edge(MemoryEdge("b", "c", "supports"))
    g.add_edge(MemoryEdge("a", "d", "supports"))
    g.add_edge(MemoryEdge("a", "c", "contradicts"))
    return g


def test_find_transitive_closure() -> None:
    """find_transitive_closure returns all reachable nodes from a start node."""
    with tempfile.TemporaryDirectory() as td:
        g = _small_graph(td)
        reachable = g.find_transitive_closure("a")
        # a can reach b, c (via b), d directly
        assert "b" in reachable
        assert "c" in reachable
        assert "d" in reachable
        assert "a" not in reachable  # start node excluded

        # Depth-limited: max_depth=2 restricts how deep BFS traverses
        shallow = g.find_transitive_closure("a", max_depth=2)
        # b and d are directly reachable; c is reachable via b
        assert "b" in shallow
        assert "d" in shallow


def test_find_transitive_closure_relation_filter() -> None:
    """find_transitive_closure respects relation_type filter."""
    with tempfile.TemporaryDirectory() as td:
        g = _small_graph(td)
        # Only traverse 'supports' edges from a
        reachable = g.find_transitive_closure("a", relation_type="supports")
        assert "b" in reachable
        assert "c" in reachable  # reachable via a→b→c
        assert "d" in reachable


def test_find_conflicts() -> None:
    """find_conflicts returns (neighbor_id, 'contradicts') pairs."""
    with tempfile.TemporaryDirectory() as td:
        g = _small_graph(td)
        conflicts = g.find_conflicts("a")
        conflict_targets = [target for target, _ in conflicts]
        assert "c" in conflict_targets
        # All returned relation_types should be 'contradicts'
        for _, rel in conflicts:
            assert rel == "contradicts"


def test_find_conflicts_empty_for_node_without_contradictions() -> None:
    """find_conflicts returns empty list for node with no contradicts edges."""
    with tempfile.TemporaryDirectory() as td:
        g = _small_graph(td)
        # Node 'b' has no contradicts edges
        assert g.find_conflicts("b") == []


def test_get_subgraph_with_confidence() -> None:
    """get_subgraph_with_confidence returns node data including confidence."""
    with tempfile.TemporaryDirectory() as td:
        g = LongTermMemoryGraph(base_dir=td)
        g.add_node(MemoryNode("root", "root node", confidence=0.9))
        g.add_node(MemoryNode("child", "child node", confidence=0.7))
        g.add_edge(MemoryEdge("root", "child", "supports"))

        result = g.get_subgraph_with_confidence("root", max_depth=2)
        # Result should contain data for root and child
        assert "root" in result
        assert "child" in result
        assert result["root"]["confidence"] == pytest.approx(0.9)
        assert result["child"]["confidence"] == pytest.approx(0.7)
