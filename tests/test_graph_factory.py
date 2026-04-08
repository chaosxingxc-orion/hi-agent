import pytest
from hi_agent.task_mgmt.graph_factory import GraphFactory, ComplexityScore
from hi_agent.contracts import TaskContract


def make_contract(goal: str = "test goal") -> TaskContract:
    from hi_agent.contracts import deterministic_id
    return TaskContract(
        task_id=deterministic_id("task"),
        goal=goal,
        task_family="general",
    )


def test_simple_task_builds_chain_without_s2_s4():
    factory = GraphFactory()
    graph = factory.build(make_contract(), ComplexityScore(score=0.2))
    node_ids = set(graph.topological_sort())
    assert "S1" in node_ids
    assert "S3" in node_ids
    assert "S5" in node_ids
    assert "S2" not in node_ids
    assert "S4" not in node_ids


def test_medium_task_builds_full_trace_chain():
    factory = GraphFactory()
    graph = factory.build(make_contract(), ComplexityScore(score=0.5))
    node_ids = set(graph.topological_sort())
    assert node_ids == {"S1", "S2", "S3", "S4", "S5"}


def test_complex_parallel_task_has_multiple_s2_nodes():
    factory = GraphFactory()
    score = ComplexityScore(score=0.8, needs_parallel_gather=True)
    graph = factory.build(make_contract(), score)
    node_ids = set(graph.topological_sort())
    parallel_nodes = [n for n in node_ids if n.startswith("S2")]
    assert len(parallel_nodes) >= 2


def test_graph_is_a_dag_no_cycles():
    factory = GraphFactory()
    for score_val in [0.2, 0.5, 0.8]:
        graph = factory.build(make_contract(), ComplexityScore(score=score_val))
        order = graph.topological_sort()
        assert len(order) > 0
