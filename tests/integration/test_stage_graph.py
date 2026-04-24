"""Tests for stage graph validation (legacy + EP-1.7)."""

from hi_agent.trajectory.stage_graph import StageGraph, default_trace_stage_graph


def test_default_trace_graph_reachable() -> None:
    """Default graph should reach S5 from S1."""
    graph = default_trace_stage_graph()
    assert graph.validate_reachability("S1_understand", "S5_review") is True


def test_graph_deadlock_detection() -> None:
    """Graph should detect deadlock for non-terminal sink nodes."""
    graph = StageGraph()
    graph.add_edge("S1", "S2")
    graph.transitions["S2"] = set()
    assert graph.has_deadlock(terminal_stages={"S3"}) is True


def test_default_trace_graph_order_is_linear_and_deterministic() -> None:
    """Default graph should expose the canonical TRACE stage order."""
    graph = default_trace_stage_graph()
    assert graph.trace_order("S1_understand") == [
        "S1_understand",
        "S2_gather",
        "S3_build",
        "S4_synthesize",
        "S5_review",
    ]


def test_trace_order_is_deterministic_for_branching_graph() -> None:
    """Traversal should be stable even when a stage has multiple successors."""
    graph = StageGraph()
    graph.add_edge("S1", "S3")
    graph.add_edge("S1", "S2")
    graph.add_edge("S2", "S4")
    graph.add_edge("S3", "S4")

    assert graph.trace_order("S1") == ["S1", "S2", "S3", "S4"]


def test_validate_all_passes_for_valid_graph() -> None:
    """Validation should pass when all checks are satisfied."""
    graph = default_trace_stage_graph()

    report = graph.validate_all(
        initial_stage="S1_understand",
        terminal_stages={"S5_review"},
    )

    assert report.is_valid is True
    assert report.unreachable_stages == []
    assert report.dead_end_stages == []
    assert report.terminal_unreachable_stages == []


def test_validate_all_fails_when_initial_stage_missing() -> None:
    """Validation should fail if initial stage does not exist."""
    graph = default_trace_stage_graph()

    report = graph.validate_all(
        initial_stage="S0_missing",
        terminal_stages={"S5_review"},
    )

    assert report.is_valid is False
    # All stages are unreachable from a non-existent initial stage.
    assert len(report.unreachable_stages) == 5


def test_validate_all_fails_on_deadlock_for_non_terminal() -> None:
    """Validation should fail if a non-terminal stage has no outgoing edges."""
    graph = StageGraph()
    graph.add_edge("S1", "S2")
    graph.transitions["S2"] = set()

    report = graph.validate_all(
        initial_stage="S1",
        terminal_stages={"S3"},
    )

    assert report.is_valid is False
    assert "S2" in report.dead_end_stages


def test_validate_all_fails_when_stage_cannot_reach_any_terminal() -> None:
    """Validation should fail if any stage cannot reach a terminal stage."""
    graph = StageGraph()
    graph.add_edge("S1", "S2")
    graph.add_edge("S2", "S3")
    graph.add_edge("S4", "S4")

    report = graph.validate_all(
        initial_stage="S1",
        terminal_stages={"S3"},
    )

    assert report.is_valid is False
    assert "S4" in report.terminal_unreachable_stages
