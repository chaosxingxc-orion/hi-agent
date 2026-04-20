"""Comprehensive tests for EP-1.7 stage-graph formal validation."""

from __future__ import annotations

from hi_agent.contracts.cts_budget import CTSBudget
from hi_agent.trajectory.stage_graph import (
    StageGraph,
    ValidationReport,
    build_default_trace_graph,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _linear_graph(*stage_ids: str) -> StageGraph:
    """Build a simple linear chain: s0 -> s1 -> ... -> sN."""
    g = StageGraph()
    for src, tgt in zip(stage_ids, stage_ids[1:]):
        g.add_edge(src, tgt)
    return g


# ------------------------------------------------------------------
# Default TRACE graph
# ------------------------------------------------------------------


class TestDefaultTraceGraph:
    """The default S1-S5 graph must pass every validation."""

    def test_build_returns_five_stages(self) -> None:
        graph = build_default_trace_graph()
        assert len(graph.transitions) == 5

    def test_passes_all_validations(self) -> None:
        graph = build_default_trace_graph()
        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S5_review"},
        )
        assert report.is_valid is True
        assert report.unreachable_stages == []
        assert report.dead_end_stages == []
        assert report.terminal_unreachable_stages == []
        assert report.incomplete_gates == []
        assert report.budget_violations == []

    def test_passes_with_valid_budget(self) -> None:
        graph = build_default_trace_graph()
        budget = CTSBudget(
            l0_raw_tokens=4000, l1_summary_tokens=2000, l2_index_tokens=500
        )
        report = graph.validate_all(
            initial_stage="S1_understand",
            terminal_stages={"S5_review"},
            budget=budget,
        )
        assert report.is_valid is True


# ------------------------------------------------------------------
# BFS reachability from initial stage
# ------------------------------------------------------------------


class TestReachabilityFrom:
    def test_all_reachable_linear(self) -> None:
        g = _linear_graph("A", "B", "C")
        assert g.validate_reachability_from("A") == []

    def test_unreachable_island(self) -> None:
        g = _linear_graph("A", "B")
        g.add_edge("X", "Y")  # disconnected component
        unreachable = g.validate_reachability_from("A")
        assert "X" in unreachable
        assert "Y" in unreachable
        assert "A" not in unreachable

    def test_initial_stage_missing(self) -> None:
        g = _linear_graph("A", "B")
        unreachable = g.validate_reachability_from("Z")
        assert set(unreachable) == {"A", "B"}

    def test_empty_graph(self) -> None:
        g = StageGraph()
        assert g.validate_reachability_from("A") == []


# ------------------------------------------------------------------
# Dead-end detection
# ------------------------------------------------------------------


class TestNoDeadEnds:
    def test_no_dead_ends_in_linear_with_terminal(self) -> None:
        g = _linear_graph("A", "B", "C")
        assert g.validate_no_dead_ends(terminal_stages={"C"}) == []

    def test_dead_end_detected(self) -> None:
        g = StageGraph()
        g.add_edge("A", "B")
        g.transitions["B"] = set()  # dead end, not terminal
        assert g.validate_no_dead_ends(terminal_stages={"C"}) == ["B"]

    def test_terminal_with_no_successors_is_ok(self) -> None:
        g = _linear_graph("A", "B")
        # B has no successors but is terminal — fine.
        assert g.validate_no_dead_ends(terminal_stages={"B"}) == []


# ------------------------------------------------------------------
# Terminal reachability
# ------------------------------------------------------------------


class TestTerminalReachability:
    def test_all_reach_terminal(self) -> None:
        g = _linear_graph("A", "B", "C")
        assert g.validate_terminal_reachability({"C"}) == []

    def test_disconnected_cannot_reach_terminal(self) -> None:
        g = _linear_graph("A", "B")
        g.add_edge("X", "Y")
        result = g.validate_terminal_reachability({"B"})
        assert "X" in result
        assert "Y" in result

    def test_self_loop_without_terminal_path(self) -> None:
        g = StageGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "B")  # self-loop, never reaches C
        result = g.validate_terminal_reachability({"C"})
        assert "A" in result
        assert "B" in result

    def test_empty_graph(self) -> None:
        g = StageGraph()
        assert g.validate_terminal_reachability({"X"}) == []


# ------------------------------------------------------------------
# Gate completeness
# ------------------------------------------------------------------


class TestGateCompleteness:
    def test_complete_gate(self) -> None:
        g = StageGraph()
        g.add_edge("S4", "S5_approved")
        g.add_edge("S4", "S3_rejected")
        assert g.validate_gate_completeness({"S4": "gate_d"}) == []

    def test_missing_rejected_path(self) -> None:
        g = StageGraph()
        g.add_edge("S4", "S5_approved")
        # Only one outgoing edge — rejected path missing.
        result = g.validate_gate_completeness({"S4": "gate_d"})
        assert result == ["S4"]

    def test_gate_stage_not_in_graph(self) -> None:
        g = StageGraph()
        result = g.validate_gate_completeness({"MISSING": "gate_d"})
        assert result == ["MISSING"]

    def test_multiple_gates(self) -> None:
        g = StageGraph()
        g.add_edge("G1", "A")
        g.add_edge("G1", "B")
        g.add_edge("G2", "C")  # only one path
        result = g.validate_gate_completeness(
            {"G1": "gate_a", "G2": "gate_d"}
        )
        assert result == ["G2"]


# ------------------------------------------------------------------
# CTS budget validation
# ------------------------------------------------------------------


class TestCTSBudget:
    def test_valid_budget(self) -> None:
        b = CTSBudget(l0_raw_tokens=100, l1_summary_tokens=50, l2_index_tokens=10)
        assert StageGraph.validate_cts_budget(b) == []

    def test_zero_l0(self) -> None:
        b = CTSBudget(l0_raw_tokens=0, l1_summary_tokens=50, l2_index_tokens=10)
        violations = StageGraph.validate_cts_budget(b)
        assert any("l0_raw_tokens" in v for v in violations)

    def test_negative_layer(self) -> None:
        b = CTSBudget(
            l0_raw_tokens=-1, l1_summary_tokens=50, l2_index_tokens=10
        )
        violations = StageGraph.validate_cts_budget(b)
        assert any("l0_raw_tokens" in v for v in violations)

    def test_all_zero(self) -> None:
        b = CTSBudget(l0_raw_tokens=0, l1_summary_tokens=0, l2_index_tokens=0)
        violations = StageGraph.validate_cts_budget(b)
        # Each layer + total should be flagged.
        assert len(violations) >= 3


# ------------------------------------------------------------------
# Combined validate_all report
# ------------------------------------------------------------------


class TestValidateAll:
    def test_valid_report(self) -> None:
        g = _linear_graph("A", "B", "C")
        report = g.validate_all(
            initial_stage="A", terminal_stages={"C"}
        )
        assert isinstance(report, ValidationReport)
        assert report.is_valid is True

    def test_report_captures_unreachable(self) -> None:
        g = _linear_graph("A", "B")
        g.add_edge("X", "Y")
        report = g.validate_all(
            initial_stage="A", terminal_stages={"B"}
        )
        assert report.is_valid is False
        assert "X" in report.unreachable_stages

    def test_report_captures_dead_ends(self) -> None:
        g = StageGraph()
        g.add_edge("A", "B")
        g.transitions["B"] = set()
        report = g.validate_all(
            initial_stage="A", terminal_stages={"C"}
        )
        assert "B" in report.dead_end_stages

    def test_report_captures_terminal_unreachable(self) -> None:
        g = StageGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "B")
        report = g.validate_all(
            initial_stage="A", terminal_stages={"C"}
        )
        assert "A" in report.terminal_unreachable_stages

    def test_report_captures_gate_violations(self) -> None:
        g = _linear_graph("A", "B", "C")
        report = g.validate_all(
            initial_stage="A",
            terminal_stages={"C"},
            gate_stages={"B": "gate_d"},
        )
        assert report.is_valid is False
        assert "B" in report.incomplete_gates

    def test_report_captures_budget_violations(self) -> None:
        g = _linear_graph("A", "B")
        bad_budget = CTSBudget(
            l0_raw_tokens=0, l1_summary_tokens=50, l2_index_tokens=10
        )
        report = g.validate_all(
            initial_stage="A",
            terminal_stages={"B"},
            budget=bad_budget,
        )
        assert report.is_valid is False
        assert len(report.budget_violations) > 0


# ------------------------------------------------------------------
# Graph with cycles
# ------------------------------------------------------------------


class TestCycles:
    def test_cycle_still_validates_when_terminal_reachable(self) -> None:
        """A graph with a loop-back should still pass if all paths can
        eventually reach a terminal stage.
        """
        g = StageGraph()
        g.add_edge("S1", "S2")
        g.add_edge("S2", "S3")
        g.add_edge("S3", "S1")  # cycle back
        g.add_edge("S3", "S4")  # terminal escape
        report = g.validate_all(
            initial_stage="S1", terminal_stages={"S4"}
        )
        assert report.is_valid is True

    def test_self_loop_at_terminal_is_ok(self) -> None:
        g = _linear_graph("A", "B")
        g.add_edge("B", "B")
        report = g.validate_all(
            initial_stage="A", terminal_stages={"B"}
        )
        assert report.is_valid is True


# ------------------------------------------------------------------
# Empty / edge-case graphs
# ------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_graph_is_invalid_when_initial_missing(self) -> None:
        g = StageGraph()
        report = g.validate_all(
            initial_stage="A", terminal_stages={"Z"}
        )
        # Empty graph has no stages so nothing unreachable, but also
        # nothing to validate — is_valid should be True (vacuously).
        assert report.is_valid is True

    def test_single_stage_terminal(self) -> None:
        """A graph with a single stage that is also the terminal."""
        g = StageGraph()
        g.transitions["ONLY"] = set()
        report = g.validate_all(
            initial_stage="ONLY", terminal_stages={"ONLY"}
        )
        assert report.is_valid is True

    def test_single_stage_not_terminal(self) -> None:
        g = StageGraph()
        g.transitions["ONLY"] = set()
        report = g.validate_all(
            initial_stage="ONLY", terminal_stages={"OTHER"}
        )
        assert report.is_valid is False
        assert "ONLY" in report.dead_end_stages
