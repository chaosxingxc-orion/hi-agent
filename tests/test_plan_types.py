# tests/test_plan_types.py
"""Tests for hi-agent Plan types and plan_to_graph() conversion."""
import pytest
from hi_agent.task_mgmt.plan_types import (
    DependencyNode,
    DependencyPlan,
    ParallelPlan,
    SequentialPlan,
    SpeculativePlan,
    plan_to_graph,
)


def test_sequential_plan_produces_chain():
    plan = SequentialPlan(node_ids=("A", "B", "C"))
    graph = plan_to_graph(plan)
    order = graph.topological_sort()
    assert order == ["A", "B", "C"]


def test_parallel_plan_groups_have_correct_dependencies():
    # group 0: [A, B], group 1: [C, D] — A and B must finish before C and D start
    plan = ParallelPlan(groups=(("A", "B"), ("C", "D")))
    graph = plan_to_graph(plan)
    order = graph.topological_sort()
    # A and B must appear before C and D
    a_pos, b_pos = order.index("A"), order.index("B")
    c_pos, d_pos = order.index("C"), order.index("D")
    assert max(a_pos, b_pos) < min(c_pos, d_pos)


def test_dependency_plan_respects_explicit_deps():
    plan = DependencyPlan(nodes=(
        DependencyNode("A"),
        DependencyNode("B", depends_on=("A",)),
        DependencyNode("C", depends_on=("A",)),
        DependencyNode("D", depends_on=("B", "C")),
    ))
    graph = plan_to_graph(plan)
    order = graph.topological_sort()
    assert order.index("A") < order.index("B")
    assert order.index("A") < order.index("C")
    assert order.index("B") < order.index("D")
    assert order.index("C") < order.index("D")


def test_speculative_plan_all_nodes_independent():
    plan = SpeculativePlan(candidate_ids=("v1", "v2", "v3"))
    graph = plan_to_graph(plan)
    nodes = set(graph.topological_sort())
    assert nodes == {"v1", "v2", "v3"}
    # No dependencies between candidates — all are entry nodes
    assert set(graph.entry_nodes) == {"v1", "v2", "v3"}


def test_graph_has_no_cycles():
    for plan in [
        SequentialPlan(node_ids=("A", "B", "C")),
        ParallelPlan(groups=(("A", "B"), ("C",))),
        DependencyPlan(nodes=(DependencyNode("X"), DependencyNode("Y", depends_on=("X",)))),
        SpeculativePlan(candidate_ids=("p", "q")),
    ]:
        graph = plan_to_graph(plan)
        assert len(graph.topological_sort()) > 0
