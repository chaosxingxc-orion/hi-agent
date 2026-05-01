"""Unit tests for hi_agent.trajectory core — Layer 1 (unit).

Covers:
  - hi_agent.trajectory.graph: TrajNode, TrajEdge, TrajectoryGraph basics
  - hi_agent.trajectory.stage_graph: StageGraph construction and validation
  - hi_agent.trajectory.node: link_parent_child DAG helper

No network, no real LLM, no external mocks.
Profile validated: default-offline
"""

from __future__ import annotations

from hi_agent.trajectory.graph import NodeState, TrajectoryGraph, TrajNode
from hi_agent.trajectory.node import link_parent_child
from hi_agent.trajectory.stage_graph import StageGraph

# ---------------------------------------------------------------------------
# TrajectoryGraph — construction helpers
# ---------------------------------------------------------------------------


class TestTrajectoryGraphChain:
    def test_as_chain_entry_terminal(self) -> None:
        """as_chain produces correct entry and terminal nodes."""
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        assert g.entry_nodes == ["A"]
        assert g.terminal_nodes == ["C"]

    def test_as_chain_topological_order(self) -> None:
        """Topological sort of a chain returns original order."""
        g = TrajectoryGraph.as_chain(["X", "Y", "Z"])
        assert g.topological_sort() == ["X", "Y", "Z"]

    def test_as_chain_single_node_is_entry_and_terminal(self) -> None:
        g = TrajectoryGraph.as_chain(["solo"])
        assert g.entry_nodes == ["solo"]
        assert g.terminal_nodes == ["solo"]


# ---------------------------------------------------------------------------
# TrajectoryGraph — node state transitions
# ---------------------------------------------------------------------------


class TestNodeStateTransitions:
    def test_pending_to_running(self) -> None:
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="n1"))
        g.update_node_state("n1", NodeState.RUNNING)
        assert g.get_node("n1").state == NodeState.RUNNING

    def test_running_to_completed_with_result(self) -> None:
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="n1"))
        g.update_node_state("n1", NodeState.COMPLETED, result={"out": 42})
        node = g.get_node("n1")
        assert node.state == NodeState.COMPLETED
        assert node.result == {"out": 42}

    def test_step_advances_first_node(self) -> None:
        g = TrajectoryGraph.as_chain(["A", "B"])
        executed = g.step()
        assert executed == ["A"]
        assert g.get_node("A").state == NodeState.COMPLETED

    def test_run_to_completion_marks_all_completed(self) -> None:
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        success = g.run_to_completion()
        assert success is True
        for nid in ["A", "B", "C"]:
            assert g.get_node(nid).state == NodeState.COMPLETED


# ---------------------------------------------------------------------------
# TrajectoryGraph — edge types
# ---------------------------------------------------------------------------


class TestEdgeTypes:
    def test_backtrack_edge_excluded_from_cycle_check(self) -> None:
        g = TrajectoryGraph.as_chain(["A", "B"])
        g.add_backtrack("B", "A")
        assert g.has_cycle(exclude_backtrack=True) is False

    def test_backtrack_counted_as_cycle_when_inclusive(self) -> None:
        g = TrajectoryGraph.as_chain(["A", "B"])
        g.add_backtrack("B", "A")
        assert g.has_cycle(exclude_backtrack=False) is True


# ---------------------------------------------------------------------------
# StageGraph — construction and reachability
# ---------------------------------------------------------------------------


class TestStageGraph:
    def test_add_edge_and_successors(self) -> None:
        sg = StageGraph()
        sg.add_edge("S1", "S2")
        sg.add_edge("S2", "S3")
        assert "S2" in sg.successors("S1")
        assert "S3" in sg.successors("S2")

    def test_reachability_true(self) -> None:
        sg = StageGraph()
        sg.add_edge("S1", "S2")
        sg.add_edge("S2", "S3")
        assert sg.validate_reachability("S1", "S3") is True

    def test_reachability_false_disconnected(self) -> None:
        sg = StageGraph()
        sg.add_edge("S1", "S2")
        sg.add_edge("X1", "X2")
        assert sg.validate_reachability("S1", "X2") is False

    def test_backtrack_edge(self) -> None:
        sg = StageGraph()
        sg.add_edge("S1", "S2")
        sg.add_backtrack("S2", "S1")
        assert sg.get_backtrack("S2") == "S1"
        assert sg.get_backtrack("S1") is None


# ---------------------------------------------------------------------------
# Node helper — link_parent_child
# ---------------------------------------------------------------------------


class TestLinkParentChild:
    def _make_node(self, nid: str):
        from hi_agent.contracts import TrajectoryNode
        from hi_agent.contracts.trajectory import NodeType

        return TrajectoryNode(
            node_id=nid,
            node_type=NodeType.ACTION,
            stage_id="S1",
            branch_id="b0",
        )

    def test_link_creates_bidirectional_relationship(self) -> None:
        dag = {nid: self._make_node(nid) for nid in ["root", "child"]}

        link_parent_child(dag, parent_id="root", child_id="child")

        assert "child" in dag["root"].children_ids
        assert "root" in dag["child"].parent_ids

    def test_link_idempotent(self) -> None:
        dag = {nid: self._make_node(nid) for nid in ["root", "child"]}

        link_parent_child(dag, parent_id="root", child_id="child")
        link_parent_child(dag, parent_id="root", child_id="child")

        assert dag["root"].children_ids.count("child") == 1
        assert dag["child"].parent_ids.count("root") == 1
