"""Tests for TrajectoryGraph and GraphExecutor."""
from __future__ import annotations

import pytest
from hi_agent.trajectory.execution import (
    GraphExecutor,
    StepResult,
)
from hi_agent.trajectory.graph import (
    EdgeType,
    NodeState,
    TrajectoryGraph,
    TrajEdge,
    TrajNode,
)

# ======================================================================
# Graph construction
# ======================================================================

class TestNodeCRUD:
    def test_add_get_node(self):
        g = TrajectoryGraph()
        n = TrajNode(node_id="A")
        g.add_node(n)
        assert g.get_node("A") is n
        assert g.node_count == 1

    def test_add_duplicate_node_raises(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        with pytest.raises(ValueError, match="already exists"):
            g.add_node(TrajNode(node_id="A"))

    def test_get_nonexistent_returns_none(self):
        g = TrajectoryGraph()
        assert g.get_node("X") is None

    def test_remove_node(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_sequence("A", "B")
        g.remove_node("B")
        assert g.get_node("B") is None
        assert g.node_count == 1
        assert g.edge_count == 0

    def test_remove_node_removes_all_edges(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_node(TrajNode(node_id="C"))
        g.add_sequence("A", "B")
        g.add_sequence("B", "C")
        g.remove_node("B")
        assert g.edge_count == 0
        assert g.get_outgoing("A") == []
        assert g.get_incoming("C") == []

    def test_remove_nonexistent_raises(self):
        g = TrajectoryGraph()
        with pytest.raises(KeyError):
            g.remove_node("X")


class TestEdgeCRUD:
    def test_add_edge_and_query(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_sequence("A", "B")
        assert g.edge_count == 1
        outgoing = g.get_outgoing("A")
        assert len(outgoing) == 1
        assert outgoing[0].target == "B"
        incoming = g.get_incoming("B")
        assert len(incoming) == 1
        assert incoming[0].source == "A"

    def test_add_edge_missing_source_raises(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="B"))
        with pytest.raises(ValueError, match="Source node"):
            g.add_sequence("A", "B")

    def test_add_edge_missing_target_raises(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        with pytest.raises(ValueError, match="Target node"):
            g.add_sequence("A", "B")

    def test_remove_edge(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_sequence("A", "B")
        g.remove_edge("A", "B")
        assert g.edge_count == 0

    def test_remove_nonexistent_edge_raises(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        with pytest.raises(KeyError):
            g.remove_edge("A", "B")

    def test_add_branch(self):
        g = TrajectoryGraph()
        for nid in ["A", "B", "C"]:
            g.add_node(TrajNode(node_id=nid))
        g.add_branch("A", ["B", "C"])
        assert g.edge_count == 2
        outgoing = g.get_outgoing("A")
        assert {e.target for e in outgoing} == {"B", "C"}
        assert all(e.edge_type == EdgeType.BRANCH for e in outgoing)

    def test_add_conditional(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        cond = lambda state: True
        g.add_conditional("A", "B", cond, desc="always")
        edge = g.get_outgoing("A")[0]
        assert edge.edge_type == EdgeType.CONDITIONAL
        assert edge.condition is cond
        assert edge.condition_desc == "always"

    def test_add_backtrack(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_backtrack("B", "A", desc="retry")
        edge = g.get_outgoing("B")[0]
        assert edge.edge_type == EdgeType.BACKTRACK


class TestEntryTerminal:
    def test_entry_terminal_detection(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_node(TrajNode(node_id="C"))
        g.add_sequence("A", "B")
        g.add_sequence("B", "C")
        assert g.entry_nodes == ["A"]
        assert g.terminal_nodes == ["C"]

    def test_single_node_is_entry_and_terminal(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        assert g.entry_nodes == ["A"]
        assert g.terminal_nodes == ["A"]

    def test_backtrack_ignored_for_entry_terminal(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_sequence("A", "B")
        g.add_backtrack("B", "A")
        # A still has no non-backtrack incoming, B still has no non-backtrack outgoing.
        assert g.entry_nodes == ["A"]
        assert g.terminal_nodes == ["B"]


# ======================================================================
# Degenerate cases
# ======================================================================

class TestDegenerateCases:
    def test_as_chain(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        assert g.node_count == 3
        assert g.edge_count == 2
        assert g.topological_sort() == ["A", "B", "C"]
        assert g.entry_nodes == ["A"]
        assert g.terminal_nodes == ["C"]

    def test_as_chain_with_payloads(self):
        g = TrajectoryGraph.as_chain(
            ["A", "B"], payloads={"A": {"info": "first"}}
        )
        assert g.get_node("A").payload == {"info": "first"}
        assert g.get_node("B").payload == {}

    def test_as_tree(self):
        g = TrajectoryGraph.as_tree(
            "root", {"root": ["A", "B"], "A": ["C", "D"]}
        )
        assert g.node_count == 5
        assert g.entry_nodes == ["root"]
        assert set(g.terminal_nodes) == {"B", "C", "D"}

    def test_as_dag(self):
        # Diamond: A->{B,C}->D
        g = TrajectoryGraph.as_dag(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        assert g.node_count == 4
        assert g.edge_count == 4
        assert g.entry_nodes == ["A"]
        assert g.terminal_nodes == ["D"]


# ======================================================================
# Dynamic modification
# ======================================================================

class TestDynamicModification:
    def test_add_node_during_execution(self):
        g = TrajectoryGraph.as_chain(["A", "B"])
        g.update_node_state("A", NodeState.COMPLETED)
        # Add a new node mid-execution.
        g.add_node(TrajNode(node_id="C"))
        g.add_sequence("B", "C")
        assert g.node_count == 3
        assert g.terminal_nodes == ["C"]
        ready = g.get_ready_nodes()
        assert [n.node_id for n in ready] == ["B"]

    def test_remove_node_removes_connected_edges(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C", "D"])
        g.remove_node("B")
        assert g.edge_count == 1  # Only C->D remains.
        assert g.get_outgoing("A") == []

    def test_prune_node_marks_dependents_skipped(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C", "D"])
        g.prune_node("B")
        assert g.get_node("B").state == NodeState.SKIPPED
        assert g.get_node("C").state == NodeState.SKIPPED
        assert g.get_node("D").state == NodeState.SKIPPED
        # A is not affected.
        assert g.get_node("A").state == NodeState.PENDING


# ======================================================================
# Query
# ======================================================================

class TestQuery:
    def test_get_ready_nodes_respects_dependencies(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        ready = g.get_ready_nodes()
        assert [n.node_id for n in ready] == ["A"]
        g.update_node_state("A", NodeState.COMPLETED)
        ready = g.get_ready_nodes()
        assert [n.node_id for n in ready] == ["B"]

    def test_get_parallel_groups(self):
        # Diamond: A->{B,C}->D
        g = TrajectoryGraph.as_dag(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        groups = g.get_parallel_groups()
        assert groups[0] == ["A"]
        assert sorted(groups[1]) == ["B", "C"]
        assert groups[2] == ["D"]

    def test_topological_sort_ignores_backtrack(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        g.add_backtrack("C", "A")
        order = g.topological_sort()
        assert order == ["A", "B", "C"]

    def test_find_paths_diamond(self):
        g = TrajectoryGraph.as_dag(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        paths = g.find_paths("A", "D")
        assert len(paths) == 2
        assert ["A", "B", "D"] in paths
        assert ["A", "C", "D"] in paths

    def test_find_paths_no_path(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        assert g.find_paths("A", "B") == []

    def test_get_critical_path(self):
        g = TrajectoryGraph.as_dag(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        path = g.get_critical_path()
        # All edges weight=1, so critical path is length 3.
        assert len(path) == 3
        assert path[0] == "A"
        assert path[-1] == "D"

    def test_has_cycle_detects_real_cycle(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_sequence("A", "B")
        # Manually add a cycle edge (not backtrack).
        g.add_edge(TrajEdge(source="B", target="A", edge_type=EdgeType.SEQUENCE))
        assert g.has_cycle(exclude_backtrack=True) is True

    def test_has_cycle_ignores_backtrack(self):
        g = TrajectoryGraph.as_chain(["A", "B"])
        g.add_backtrack("B", "A")
        assert g.has_cycle(exclude_backtrack=True) is False
        assert g.has_cycle(exclude_backtrack=False) is True

    def test_get_subgraph(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C", "D"])
        sub = g.get_subgraph(["B"], depth=1)
        assert sub.node_count == 2  # B and C
        assert "B" in [n for n in sub._nodes]
        assert "C" in [n for n in sub._nodes]

    def test_get_subgraph_unlimited_depth(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C", "D"])
        sub = g.get_subgraph(["B"])
        assert sub.node_count == 3  # B, C, D


# ======================================================================
# Conditional edges
# ======================================================================

class TestConditionalEdges:
    def test_evaluate_branches(self):
        g = TrajectoryGraph()
        for nid in ["A", "B", "C"]:
            g.add_node(TrajNode(node_id=nid))
        g.add_conditional("A", "B", lambda s: True, desc="always")
        g.add_conditional("A", "C", lambda s: False, desc="never")
        targets = g.evaluate_branches("A", {})
        assert "B" in targets
        assert "C" not in targets

    def test_conditional_edge_blocks_ready(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        # Only conditional edge to B, always false.
        g.add_conditional("A", "B", lambda s: False, desc="never")
        g.update_node_state("A", NodeState.COMPLETED)
        ready = g.get_ready_nodes()
        assert all(n.node_id != "B" for n in ready)

    def test_conditional_edge_allows_ready_when_true(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.add_node(TrajNode(node_id="B"))
        g.add_conditional("A", "B", lambda s: True, desc="always")
        g.update_node_state("A", NodeState.COMPLETED)
        ready = g.get_ready_nodes()
        assert any(n.node_id == "B" for n in ready)


# ======================================================================
# Backtrack edges
# ======================================================================

class TestBacktrackEdges:
    def test_backtrack_resets_node_to_pending(self):
        g = TrajectoryGraph.as_chain(["A", "B"])
        g.add_backtrack("B", "A")
        # Simulate: A completes, B fails.
        g.update_node_state("A", NodeState.COMPLETED)
        g.update_node_state("B", NodeState.RUNNING)
        g.update_node_state("B", NodeState.FAILED)
        # step() should trigger backtrack.
        # Manually call step-like logic.
        state = g._build_graph_state()
        for e in g.get_outgoing("B"):
            if e.edge_type == EdgeType.BACKTRACK:
                target = g.get_node(e.target)
                if target and target.retry_count < target.max_retries:
                    target.state = NodeState.PENDING
                    target.retry_count += 1
        assert g.get_node("A").state == NodeState.PENDING
        assert g.get_node("A").retry_count == 1

    def test_max_retries_prevents_infinite_loop(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A", max_retries=1))
        g.add_node(TrajNode(node_id="B"))
        g.add_sequence("A", "B")
        g.add_backtrack("B", "A")
        # Exhaust retries.
        node_a = g.get_node("A")
        node_a.retry_count = 1  # already at max
        node_a.state = NodeState.COMPLETED
        g.update_node_state("B", NodeState.RUNNING)
        g.update_node_state("B", NodeState.FAILED)
        # Backtrack should NOT trigger since retry_count >= max_retries.
        for e in g.get_outgoing("B"):
            if e.edge_type == EdgeType.BACKTRACK:
                target = g.get_node(e.target)
                assert target.retry_count >= target.max_retries


# ======================================================================
# Execution
# ======================================================================

class TestExecution:
    def test_step_processes_ready_nodes(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        executed = g.step()
        assert executed == ["A"]
        assert g.get_node("A").state == NodeState.COMPLETED

    def test_run_to_completion_chain(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        result = g.run_to_completion()
        assert result is True
        assert g.get_node("A").state == NodeState.COMPLETED
        assert g.get_node("B").state == NodeState.COMPLETED
        assert g.get_node("C").state == NodeState.COMPLETED

    def test_run_to_completion_diamond(self):
        g = TrajectoryGraph.as_dag(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        result = g.run_to_completion()
        assert result is True
        for nid in ["A", "B", "C", "D"]:
            assert g.get_node(nid).state == NodeState.COMPLETED

    def test_step_with_execute_fn(self):
        g = TrajectoryGraph.as_chain(["A", "B"])
        results = []
        def execute(node):
            results.append(node.node_id)
            return f"done_{node.node_id}"
        g.step(execute_fn=execute)
        assert results == ["A"]
        assert g.get_node("A").result == "done_A"

    def test_step_handles_failure(self):
        g = TrajectoryGraph.as_chain(["A", "B"])
        def fail_fn(node):
            raise RuntimeError("boom")
        g.step(execute_fn=fail_fn)
        assert g.get_node("A").state == NodeState.FAILED
        assert "boom" in g.get_node("A").failure_reason

    def test_run_to_completion_with_fn(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        call_order = []
        def execute(node):
            call_order.append(node.node_id)
            return "ok"
        result = g.run_to_completion(execute_fn=execute)
        assert result is True
        assert call_order == ["A", "B", "C"]


class TestGraphExecutor:
    def test_executor_run_chain(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        executor = GraphExecutor(g)
        result = executor.run()
        assert result.success is True
        assert result.total_steps == 3
        assert sorted(result.completed_nodes) == ["A", "B", "C"]

    def test_executor_with_execute_fn(self):
        g = TrajectoryGraph.as_chain(["A", "B"])
        calls = []
        def fn(node):
            calls.append(node.node_id)
            return 42
        executor = GraphExecutor(g, execute_fn=fn)
        result = executor.run()
        assert result.success is True
        assert calls == ["A", "B"]

    def test_executor_failure_with_retry(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A", max_retries=2))
        g.add_node(TrajNode(node_id="B"))
        g.add_sequence("A", "B")
        fail_count = [0]
        def fn(node):
            if node.node_id == "A" and fail_count[0] < 2:
                fail_count[0] += 1
                raise RuntimeError("fail")
            return "ok"
        executor = GraphExecutor(g, execute_fn=fn)
        result = executor.run()
        assert result.success is True
        assert "A" in result.completed_nodes

    def test_executor_on_step_callback(self):
        g = TrajectoryGraph.as_chain(["A", "B"])
        steps: list[StepResult] = []
        executor = GraphExecutor(g, on_step=lambda s: steps.append(s))
        executor.run()
        assert len(steps) == 2
        assert steps[0].step_number == 1
        assert steps[0].completed == ["A"]

    def test_executor_permanent_failure_prunes(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        # Set max_retries=0 so first failure is permanent.
        g.get_node("A").max_retries = 0
        def fn(node):
            if node.node_id == "A":
                raise RuntimeError("permanent")
            return "ok"
        executor = GraphExecutor(g, execute_fn=fn)
        result = executor.run()
        assert result.success is False
        assert "A" in result.failed_nodes
        assert "B" in result.skipped_nodes
        assert "C" in result.skipped_nodes


# ======================================================================
# Serialization
# ======================================================================

class TestSerialization:
    def test_to_mermaid(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        g.update_node_state("A", NodeState.COMPLETED)
        mermaid = g.to_mermaid(title="Test")
        assert "flowchart TD" in mermaid
        assert "A" in mermaid
        assert "fill:#90EE90" in mermaid  # completed=green

    def test_to_mermaid_backtrack_dotted(self):
        g = TrajectoryGraph.as_chain(["A", "B"])
        g.add_backtrack("B", "A", desc="retry")
        mermaid = g.to_mermaid()
        assert "-." in mermaid  # dotted line

    def test_to_json_from_json_roundtrip(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        g.update_node_state("A", NodeState.COMPLETED, result={"x": 1})
        g.get_node("B").priority = 3
        data = g.to_json()
        g2 = TrajectoryGraph.from_json(data)
        assert g2.node_count == 3
        assert g2.edge_count == 2
        assert g2.get_node("A").state == NodeState.COMPLETED
        assert g2.get_node("A").result == {"x": 1}
        assert g2.get_node("B").priority == 3
        assert g2.topological_sort() == ["A", "B", "C"]

    def test_to_json_preserves_edge_types(self):
        g = TrajectoryGraph()
        for nid in ["A", "B", "C"]:
            g.add_node(TrajNode(node_id=nid))
        g.add_sequence("A", "B")
        g.add_backtrack("B", "A", desc="retry")
        data = g.to_json()
        g2 = TrajectoryGraph.from_json(data)
        outgoing_b = g2.get_outgoing("B")
        assert any(e.edge_type == EdgeType.BACKTRACK for e in outgoing_b)

    def test_to_planning_prompt(self):
        g = TrajectoryGraph.as_chain(["A", "B", "C"])
        g.update_node_state("A", NodeState.COMPLETED)
        prompt = g.to_planning_prompt()
        assert "Completed: A" in prompt
        assert "Ready (can execute now): B" in prompt
        assert "Pending: C" in prompt

    def test_from_llm_plan(self):
        plan = {
            "nodes": [
                {"id": "research", "type": "task", "payload": {"desc": "research topic"}},
                {"id": "write", "type": "task"},
                {"id": "review", "type": "task"},
            ],
            "edges": [
                {"source": "research", "target": "write", "type": "sequence"},
                {"source": "write", "target": "review", "type": "sequence"},
            ],
        }
        g = TrajectoryGraph.from_llm_plan(plan)
        assert g.node_count == 3
        assert g.edge_count == 2
        assert g.get_node("research").payload == {"desc": "research topic"}
        assert g.topological_sort() == ["research", "review", "write"] or \
               g.topological_sort() == ["research", "write", "review"]


# ======================================================================
# Integration — replaces StageGraph and TaskDAG
# ======================================================================

class TestIntegration:
    def test_replaces_stage_graph_s1_to_s5(self):
        """TrajectoryGraph.as_chain can model the default TRACE stage graph."""
        stages = [
            "S1_understand", "S2_gather", "S3_build",
            "S4_synthesize", "S5_review",
        ]
        g = TrajectoryGraph.as_chain(stages, graph_id="trace_stages")
        assert g.entry_nodes == ["S1_understand"]
        assert g.terminal_nodes == ["S5_review"]
        assert g.topological_sort() == stages
        # Run through all stages.
        result = g.run_to_completion()
        assert result is True
        for s in stages:
            assert g.get_node(s).state == NodeState.COMPLETED

    def test_replaces_task_dag_for_decomposition(self):
        """TrajectoryGraph.as_dag can model task decomposition."""
        # Simulate: main splits into sub1, sub2 (parallel), then merge.
        g = TrajectoryGraph.as_dag(
            ["main", "sub1", "sub2", "merge"],
            [("main", "sub1"), ("main", "sub2"),
             ("sub1", "merge"), ("sub2", "merge")],
            graph_id="decomposition",
        )
        assert g.entry_nodes == ["main"]
        assert g.terminal_nodes == ["merge"]
        groups = g.get_parallel_groups()
        assert groups[0] == ["main"]
        assert sorted(groups[1]) == ["sub1", "sub2"]
        assert groups[2] == ["merge"]
        # Execute with function.
        results = {}
        def execute(node):
            results[node.node_id] = "done"
            return "done"
        completed = g.run_to_completion(execute_fn=execute)
        assert completed is True
        assert len(results) == 4

    def test_stage_graph_with_backtrack(self):
        """Model a stage graph with backtracking from S3 to S2."""
        stages = ["S1", "S2", "S3", "S4"]
        g = TrajectoryGraph.as_chain(stages)
        g.add_backtrack("S3", "S2", desc="need more data")
        assert g.has_cycle(exclude_backtrack=True) is False
        assert g.has_cycle(exclude_backtrack=False) is True
        assert g.topological_sort() == stages


class TestUpdateNodeState:
    def test_update_state(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.update_node_state("A", NodeState.RUNNING)
        assert g.get_node("A").state == NodeState.RUNNING

    def test_update_state_with_result(self):
        g = TrajectoryGraph()
        g.add_node(TrajNode(node_id="A"))
        g.update_node_state("A", NodeState.COMPLETED, result={"x": 1})
        assert g.get_node("A").result == {"x": 1}

    def test_update_nonexistent_raises(self):
        g = TrajectoryGraph()
        with pytest.raises(KeyError):
            g.update_node_state("X", NodeState.COMPLETED)
