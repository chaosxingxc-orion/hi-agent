"""Tests for the task decomposition engine."""

from __future__ import annotations

import pytest
from hi_agent.contracts import TaskContract
from hi_agent.task_decomposition.dag import TaskDAG, TaskNode, TaskNodeState
from hi_agent.task_decomposition.decomposer import TaskDecomposer
from hi_agent.task_decomposition.executor import DAGExecutor, DAGResult
from hi_agent.task_decomposition.feedback import DecompositionFeedback

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contract(tid: str = "t1", goal: str = "do stuff") -> TaskContract:
    return TaskContract(task_id=tid, goal=goal)


def _node(nid: str, deps: list[str] | None = None) -> TaskNode:
    return TaskNode(
        node_id=nid,
        task_contract=_contract(nid),
        dependencies=deps or [],
    )


# ---------------------------------------------------------------------------
# TaskDAG — structure
# ---------------------------------------------------------------------------


class TestTaskDAGStructure:
    """Node/edge management and structural queries."""

    def test_add_node(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        assert "a" in dag.nodes

    def test_add_duplicate_node_raises(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        with pytest.raises(ValueError, match="already exists"):
            dag.add_node(_node("a"))

    def test_add_edge(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_edge("a", "b")
        node_b = dag.get_node("b")
        assert "a" in node_b.dependencies

    def test_add_edge_unknown_source_raises(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("b"))
        with pytest.raises(ValueError, match="Source node"):
            dag.add_edge("a", "b")

    def test_add_edge_unknown_target_raises(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        with pytest.raises(ValueError, match="Target node"):
            dag.add_edge("a", "b")

    def test_get_node_missing_raises(self) -> None:
        dag = TaskDAG()
        with pytest.raises(KeyError):
            dag.get_node("nope")


# ---------------------------------------------------------------------------
# TaskDAG — cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    """Cycle detection and prevention."""

    def test_no_cycle_in_chain(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_node(_node("c"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        assert not dag.has_cycle()

    def test_add_edge_creating_cycle_raises(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_edge("a", "b")
        with pytest.raises(ValueError, match="cycle"):
            dag.add_edge("b", "a")

    def test_has_cycle_false_for_empty(self) -> None:
        dag = TaskDAG()
        assert not dag.has_cycle()

    def test_self_loop_detected(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        with pytest.raises(ValueError, match="cycle"):
            dag.add_edge("a", "a")


# ---------------------------------------------------------------------------
# TaskDAG — topological sort
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    """Topological ordering."""

    def test_linear_chain(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_node(_node("c"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        order = dag.topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond(self) -> None:
        dag = TaskDAG()
        for nid in ("a", "b", "c", "d"):
            dag.add_node(_node(nid))
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        dag.add_edge("b", "d")
        dag.add_edge("c", "d")
        order = dag.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_single_node(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("only"))
        assert dag.topological_sort() == ["only"]


# ---------------------------------------------------------------------------
# TaskDAG — ready nodes and state transitions
# ---------------------------------------------------------------------------


class TestReadyNodesAndState:
    """get_ready_nodes and mark_* transitions."""

    def test_root_nodes_are_ready(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_edge("a", "b")
        ready = dag.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].node_id == "a"

    def test_dependent_becomes_ready_after_dep_completes(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_edge("a", "b")

        dag.mark_running("a")
        dag.mark_completed("a")
        ready = dag.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].node_id == "b"

    def test_mark_running_invalid_state_raises(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.mark_running("a")
        dag.mark_completed("a")
        with pytest.raises(ValueError, match="Cannot mark"):
            dag.mark_running("a")

    def test_mark_completed_requires_running(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        with pytest.raises(ValueError, match="Cannot mark"):
            dag.mark_completed("a")

    def test_mark_failed_sets_reason(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.mark_running("a")
        dag.mark_failed("a", "oops")
        assert dag.get_node("a").state == TaskNodeState.FAILED
        assert dag.get_node("a").failure_reason == "oops"


# ---------------------------------------------------------------------------
# TaskDAG — subgraph extraction
# ---------------------------------------------------------------------------


class TestSubgraph:
    """get_subgraph extracts valid independent sub-DAGs."""

    def test_subgraph_includes_dependents(self) -> None:
        dag = TaskDAG()
        for nid in ("a", "b", "c", "d"):
            dag.add_node(_node(nid))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        dag.add_edge("a", "d")

        sub = dag.get_subgraph(["b"])
        assert "b" in sub.nodes
        assert "c" in sub.nodes
        # "a" is not a dependent of "b", should not be included.
        assert "a" not in sub.nodes
        # "d" is not reachable from "b".
        assert "d" not in sub.nodes

    def test_subgraph_is_valid(self) -> None:
        dag = TaskDAG()
        for nid in ("a", "b", "c"):
            dag.add_node(_node(nid))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        sub = dag.get_subgraph(["a"])
        assert sub.validate() == []

    def test_subgraph_missing_root_raises(self) -> None:
        dag = TaskDAG()
        with pytest.raises(KeyError):
            dag.get_subgraph(["missing"])


# ---------------------------------------------------------------------------
# TaskDAG — parallel groups
# ---------------------------------------------------------------------------


class TestParallelGroups:
    """get_parallel_groups returns correct parallelism levels."""

    def test_linear_chain_one_per_group(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_node(_node("c"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        groups = dag.get_parallel_groups()
        assert groups == [["a"], ["b"], ["c"]]

    def test_diamond_has_parallel_middle(self) -> None:
        dag = TaskDAG()
        for nid in ("a", "b", "c", "d"):
            dag.add_node(_node(nid))
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        dag.add_edge("b", "d")
        dag.add_edge("c", "d")
        groups = dag.get_parallel_groups()
        assert groups[0] == ["a"]
        assert set(groups[1]) == {"b", "c"}
        assert groups[2] == ["d"]

    def test_empty_dag(self) -> None:
        dag = TaskDAG()
        assert dag.get_parallel_groups() == []

    def test_all_independent(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("x"))
        dag.add_node(_node("y"))
        dag.add_node(_node("z"))
        # No edges — but validate will flag orphans; parallel groups still work.
        groups = dag.get_parallel_groups()
        assert len(groups) == 1
        assert set(groups[0]) == {"x", "y", "z"}


# ---------------------------------------------------------------------------
# TaskDAG — validate
# ---------------------------------------------------------------------------


class TestValidate:
    """DAG validation catches issues."""

    def test_empty_dag(self) -> None:
        dag = TaskDAG()
        issues = dag.validate()
        assert any("no nodes" in i for i in issues)

    def test_valid_dag_no_issues(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_edge("a", "b")
        assert dag.validate() == []

    def test_orphan_detected(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_node(_node("orphan"))
        dag.add_edge("a", "b")
        issues = dag.validate()
        assert any("orphan" in i.lower() for i in issues)

    def test_is_complete(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.mark_running("a")
        dag.mark_completed("a")
        assert dag.is_complete()

    def test_is_failed(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.mark_running("a")
        dag.mark_failed("a", "boom")
        assert dag.is_failed()


# ---------------------------------------------------------------------------
# TaskDecomposer — linear strategy
# ---------------------------------------------------------------------------


class TestDecomposerLinear:
    """TaskDecomposer.decompose with linear strategy."""

    def test_linear_produces_five_stages(self) -> None:
        contract = TaskContract(
            task_id="root",
            goal="Build a widget",
            decomposition_strategy="linear",
        )
        decomposer = TaskDecomposer()
        dag = decomposer.decompose(contract)

        nodes = dag.nodes
        assert len(nodes) == 5

    def test_linear_is_a_chain(self) -> None:
        contract = TaskContract(
            task_id="root",
            goal="Build a widget",
            decomposition_strategy="linear",
        )
        decomposer = TaskDecomposer()
        dag = decomposer.decompose(contract)
        groups = dag.get_parallel_groups()
        # Each group should have exactly 1 node (sequential).
        assert all(len(g) == 1 for g in groups)
        assert len(groups) == 5

    def test_linear_nodes_inherit_parent(self) -> None:
        contract = TaskContract(
            task_id="root",
            goal="Build a widget",
            risk_level="high",
            decomposition_strategy="linear",
        )
        decomposer = TaskDecomposer()
        dag = decomposer.decompose(contract)
        for node in dag.nodes.values():
            assert node.task_contract.parent_task_id == "root"
            assert node.task_contract.risk_level == "high"

    def test_default_strategy_is_linear(self) -> None:
        contract = TaskContract(task_id="root", goal="Do things")
        decomposer = TaskDecomposer()
        dag = decomposer.decompose(contract)
        assert len(dag.nodes) == 5

    def test_dag_strategy_produces_parallel_groups(self) -> None:
        contract = TaskContract(
            task_id="root",
            goal="Complex work",
            decomposition_strategy="dag",
        )
        decomposer = TaskDecomposer()
        dag = decomposer.decompose(contract)
        groups = dag.get_parallel_groups()
        # The heuristic DAG has understand -> (gather, build) -> synthesize -> review
        assert len(dag.nodes) == 5
        # At least one group should have >1 node (parallel).
        assert any(len(g) > 1 for g in groups)


# ---------------------------------------------------------------------------
# DAGExecutor — run to completion
# ---------------------------------------------------------------------------


class TestDAGExecutor:
    """DAGExecutor with mock execute_fn."""

    def _simple_dag(self) -> TaskDAG:
        dag = TaskDAG()
        dag.add_node(_node("a"))
        dag.add_node(_node("b"))
        dag.add_node(_node("c"))
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        return dag

    def test_run_to_completion_success(self) -> None:
        dag = self._simple_dag()
        executor = DAGExecutor(
            dag,
            execute_fn=lambda n: {"ok": True},
        )
        result = executor.run_to_completion()
        assert result.success
        assert len(result.completed_nodes) == 3
        assert result.failed_nodes == []

    def test_run_to_completion_with_failure(self) -> None:
        dag = self._simple_dag()

        def execute(node: TaskNode) -> dict:
            if node.node_id == "b":
                raise RuntimeError("b exploded")
            return {"ok": True}

        executor = DAGExecutor(dag, execute_fn=execute)
        result = executor.run_to_completion()
        assert not result.success
        assert "b" in result.failed_nodes

    def test_progress_callback_invoked(self) -> None:
        dag = TaskDAG()
        dag.add_node(_node("a"))

        progress_calls: list = []
        executor = DAGExecutor(
            dag,
            execute_fn=lambda n: {"ok": True},
            on_progress=lambda p: progress_calls.append(p),
        )
        executor.run_to_completion()
        assert len(progress_calls) >= 1

    def test_step_terminal_on_empty_dag(self) -> None:
        dag = TaskDAG()
        executor = DAGExecutor(dag)
        result = executor.step()
        assert result.is_terminal


# ---------------------------------------------------------------------------
# DAGExecutor — rollback
# ---------------------------------------------------------------------------


class TestRollback:
    """Rollback cascades correctly."""

    def test_compensate_rollback_direct_deps(self) -> None:
        dag = TaskDAG()
        a = _node("a")
        b = _node("b")
        b.rollback_policy = "compensate"
        dag.add_node(a)
        dag.add_node(b)
        dag.add_edge("a", "b")

        # Complete "a", then fail "b".
        dag.mark_running("a")
        dag.mark_completed("a")
        dag.mark_running("b")
        dag.mark_failed("b", "broke")

        executor = DAGExecutor(dag)
        rolled = executor.rollback("b")
        assert "a" in rolled
        assert dag.get_node("a").state == TaskNodeState.ROLLED_BACK

    def test_cascade_rollback_transitive(self) -> None:
        dag = TaskDAG()
        a = _node("a")
        b = _node("b")
        c = _node("c")
        c.rollback_policy = "cascade"
        dag.add_node(a)
        dag.add_node(b)
        dag.add_node(c)
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")

        dag.mark_running("a")
        dag.mark_completed("a")
        dag.mark_running("b")
        dag.mark_completed("b")
        dag.mark_running("c")
        dag.mark_failed("c", "cascade test")

        executor = DAGExecutor(dag)
        rolled = executor.rollback("c")
        assert "b" in rolled
        assert "a" in rolled

    def test_none_rollback_does_nothing(self) -> None:
        dag = TaskDAG()
        a = _node("a")
        b = _node("b")
        b.rollback_policy = "none"
        dag.add_node(a)
        dag.add_node(b)
        dag.add_edge("a", "b")

        dag.mark_running("a")
        dag.mark_completed("a")
        dag.mark_running("b")
        dag.mark_failed("b", "no rollback")

        executor = DAGExecutor(dag)
        rolled = executor.rollback("b")
        assert rolled == []
        assert dag.get_node("a").state == TaskNodeState.COMPLETED


# ---------------------------------------------------------------------------
# DecompositionFeedback
# ---------------------------------------------------------------------------


class TestDecompositionFeedback:
    """Feedback collection and strategy recommendation."""

    def test_recommend_with_no_data_returns_linear(self) -> None:
        fb = DecompositionFeedback()
        assert fb.recommend_strategy("unknown") == "linear"

    def test_recommend_picks_best_strategy(self) -> None:
        fb = DecompositionFeedback()

        # Record several successes for "dag" and failures for "linear".
        success_result = DAGResult(
            success=True,
            completed_nodes=["a", "b"],
            total_steps=2,
        )
        failure_result = DAGResult(
            success=False,
            completed_nodes=["a"],
            failed_nodes=["b"],
            total_steps=2,
        )

        fb.record("analysis", "dag", success_result)
        fb.record("analysis", "dag", success_result)
        fb.record("analysis", "linear", failure_result)
        fb.record("analysis", "linear", failure_result)

        assert fb.recommend_strategy("analysis") == "dag"

    def test_get_stats_empty(self) -> None:
        fb = DecompositionFeedback()
        stats = fb.get_stats()
        assert stats["total_records"] == 0

    def test_get_stats_filtered(self) -> None:
        fb = DecompositionFeedback()
        result = DAGResult(
            success=True,
            completed_nodes=["a"],
            total_steps=1,
        )
        fb.record("family_a", "linear", result)
        fb.record("family_b", "dag", result)

        stats_a = fb.get_stats("family_a")
        assert stats_a["total_records"] == 1

        stats_all = fb.get_stats()
        assert stats_all["total_records"] == 2
