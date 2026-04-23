"""Acceptance tests for P-3: project_id-scoped L3 memory aggregation.

Two runs within the same project must share L3 long-term memory. Two runs
in different projects must be isolated. The storage contract is the
LongTermMemoryGraph's on-disk layout ({base}/L3/{profile}/{project}/graph.json).

These tests drive through the public API only: they instantiate
LongTermMemoryGraph with the same (base_dir, profile_id, project_id)
from two independent "runs" and verify the second sees the first's nodes.
"""

from __future__ import annotations

import tempfile

from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode
from hi_agent.session.run_session import RunSession


def _make_graph(base_dir: str, project_id: str, profile_id: str = "p-1") -> LongTermMemoryGraph:
    """Build a graph as a run would: same profile, explicit project_id."""
    return LongTermMemoryGraph(
        base_dir=base_dir,
        profile_id=profile_id,
        project_id=project_id,
    )


def test_two_runs_same_project_share_l3() -> None:
    """Run 1 writes a fact; Run 2 in the same project sees it."""
    project_id = "test-project-aggregation"

    with tempfile.TemporaryDirectory() as base_dir:
        # Run 1: simulate a run session and write a L3 fact
        session_1 = RunSession(run_id="run-1", project_id=project_id)
        assert session_1.project_id == project_id

        graph_1 = _make_graph(base_dir, project_id)
        graph_1.add_node(
            MemoryNode(
                node_id="fact-001",
                content="Paris is the capital of France",
                node_type="fact",
                tags=["geography", project_id],
                source_sessions=[session_1.run_id],
            )
        )
        graph_1.save()

        # Run 2: new session, same project, fresh graph instance
        session_2 = RunSession(run_id="run-2", project_id=project_id)
        assert session_2.project_id == project_id

        graph_2 = _make_graph(base_dir, project_id)

        # Run 2 must see run 1's fact
        fact = graph_2.get_node("fact-001")
        assert fact is not None, "Run 2 could not read Run 1's L3 fact"
        assert fact.content == "Paris is the capital of France"
        assert "run-1" in fact.source_sessions

        # And it must be discoverable by search
        results = graph_2.search("Paris")
        assert any(n.node_id == "fact-001" for n in results)


def test_two_runs_different_projects_isolated() -> None:
    """A fact written under project A must NOT leak into project B."""
    with tempfile.TemporaryDirectory() as base_dir:
        graph_a = _make_graph(base_dir, project_id="project-a")
        graph_a.add_node(
            MemoryNode(
                node_id="secret-fact",
                content="Project A internal datum",
                node_type="fact",
                tags=["internal"],
                source_sessions=["run-a-1"],
            )
        )
        graph_a.save()

        graph_b = _make_graph(base_dir, project_id="project-b")

        # Different project -> cannot read A's node
        assert graph_b.get_node("secret-fact") is None
        assert graph_b.node_count() == 0
        assert graph_b.search("internal") == []


def test_project_id_in_storage_path() -> None:
    """Storage path must include project_id as a directory component.

    This is the mechanism by which isolation and aggregation are enforced:
    same project_id -> same directory -> shared file; different project_id
    -> different directory -> isolated files.
    """
    with tempfile.TemporaryDirectory() as base_dir:
        graph = _make_graph(base_dir, project_id="proj-xyz")
        path_str = str(graph._storage_path)
        assert "proj-xyz" in path_str
        assert "p-1" in path_str  # profile dir still present


def test_third_run_joins_existing_project() -> None:
    """Verify the aggregation extends beyond two runs."""
    project_id = "long-running-project"

    with tempfile.TemporaryDirectory() as base_dir:
        # Run 1 writes fact A
        g1 = _make_graph(base_dir, project_id)
        g1.add_node(MemoryNode(node_id="a", content="alpha", source_sessions=["r1"]))
        g1.save()

        # Run 2 writes fact B
        g2 = _make_graph(base_dir, project_id)
        assert g2.get_node("a") is not None
        g2.add_node(MemoryNode(node_id="b", content="beta", source_sessions=["r2"]))
        g2.save()

        # Run 3 sees both
        g3 = _make_graph(base_dir, project_id)
        assert g3.get_node("a") is not None
        assert g3.get_node("b") is not None
        assert g3.node_count() == 2
